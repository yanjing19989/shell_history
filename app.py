from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)


@dataclass
class Record:
    id: str
    command: str
    timestamp: Optional[str]
    shell: str
    source_file: str
    line_number: int


class Adapter:
    name = ""
    label = ""

    def candidates(self):
        return []

    def detect(self):
        for p in self.candidates():
            if p.exists() and p.is_file():
                return p
        return None

    def parse(self, path: Path):
        raw, encoding = read_text(path)
        return self.parse_text(raw, path), encoding

    def parse_text(self, text, path):
        records = []
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                records.append(Record(f"{self.name}:{i}", line, None, self.name, str(path), i))
        return records

    def serialize(self, records):
        return "\n".join(r.command for r in records) + ("\n" if records else "")


class PowerShellAdapter(Adapter):
    name, label = "powershell", "PowerShell"

    def candidates(self):
        appdata = os.environ.get("APPDATA")
        home = Path.home()
        out = []
        if appdata:
            out.append(Path(appdata) / "Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt")
        out.extend([
            home / "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt",
            home / ".local/share/powershell/PSReadLine/ConsoleHost_history.txt",
        ])
        return out


class BashAdapter(Adapter):
    name, label = "bash", "Bash"

    def candidates(self):
        return [Path(os.environ.get("HISTFILE", ""))] if os.environ.get("HISTFILE") else [Path.home() / ".bash_history"]


class ZshAdapter(Adapter):
    name, label = "zsh", "Zsh"
    _header = re.compile(r": (\d+):\d+;?(.*)")

    def candidates(self):
        return [Path(os.environ.get("HISTFILE", ""))] if os.environ.get("HISTFILE") else [Path.home() / ".zsh_history"]

    def parse_text(self, text, path):
        records = []
        for i, line in enumerate(text.splitlines(), 1):
            ts = None
            command = line
            m = self._header.match(line)
            if m:
                try:
                    ts = datetime.fromtimestamp(int(m.group(1)), timezone.utc).isoformat()
                except ValueError:
                    pass
                command = m.group(2)
            if command.strip():
                records.append(Record(f"{self.name}:{i}", command, ts, self.name, str(path), i))
        return records

    def serialize(self, records):
        return "\n".join((f": {int(datetime.fromisoformat(r.timestamp).timestamp())}:0;{r.command}" if r.timestamp else r.command) for r in records) + ("\n" if records else "")


class CmdAdapter(Adapter):
    name, label = "cmd", "Command Prompt"

    def candidates(self):
        # cmd.exe has no standard persistent history file; support common user-configured paths.
        vals = [os.environ.get("CMD_HISTORY_FILE"), os.environ.get("CMDER_HISTORY")]
        return [Path(v) for v in vals if v]


ADAPTERS = {a.name: a for a in [PowerShellAdapter(), CmdAdapter(), BashAdapter(), ZshAdapter()]}
_lock = threading.Lock()


def read_text(path):
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", os.device_encoding(1) or "cp1252"):
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def stats(records):
    counts = {}
    for r in records:
        counts[r.command] = counts.get(r.command, 0) + 1
    return {"total": len(records), "unique": len(counts), "duplicates": sum(v - 1 for v in counts.values() if v > 1), "with_timestamp": sum(bool(r.timestamp) for r in records)}


def payload(records):
    return {"records": [asdict(r) for r in records], "stats": stats(records)}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/shells")
def shells():
    return jsonify({"shells": [{"name": a.name, "label": a.label, "path": str(a.detect()) if a.detect() else None, "available": bool(a.detect())} for a in ADAPTERS.values()]})


@app.get("/api/history")
def history():
    name = request.args.get("shell", "")
    adapter = ADAPTERS.get(name)
    if not adapter:
        return jsonify({"error": "unknown shell"}), 400
    path = Path(request.args.get("path") or adapter.detect() or "")
    if not path or not path.is_file():
        return jsonify({"error": "history file not found", "shell": name}), 404
    try:
        records, encoding = adapter.parse(path)
        result = payload(records)
        result.update({"shell": name, "path": str(path), "encoding": encoding})
        return jsonify(result)
    except OSError as exc:
        return jsonify({"error": str(exc)}), 400


def records_from_json(items, shell, path):
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("command"), str):
            continue
        out.append(Record(str(item.get("id", "")), item["command"], item.get("timestamp"), shell, str(path), int(item.get("line_number", 0))))
    return out


@app.post("/api/history/preview")
def preview():
    body = request.get_json(silent=True) or {}
    shell, path = body.get("shell"), body.get("path")
    adapter = ADAPTERS.get(shell)
    if not adapter or not path:
        return jsonify({"error": "shell and path are required"}), 400
    records = records_from_json(body.get("records", []), shell, path)
    return jsonify({"path": path, "shell": shell, "count": len(records), "stats": stats(records), "content": adapter.serialize(records)})


@app.post("/api/history/save")
def save():
    body = request.get_json(silent=True) or {}
    shell, path_value = body.get("shell"), body.get("path")
    adapter = ADAPTERS.get(shell)
    if not adapter or not path_value:
        return jsonify({"error": "shell and path are required"}), 400
    path = Path(path_value).expanduser()
    if not path.is_file():
        return jsonify({"error": "history file not found"}), 404
    records = records_from_json(body.get("records", []), shell, path)
    content = adapter.serialize(records)
    with _lock:
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = path.with_name(path.name + f".bak-{stamp}")
            shutil.copy2(path, backup)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            return jsonify({"ok": True, "backup": str(backup), "path": str(path), "stats": stats(records)})
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    threading.Timer(0.8, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
