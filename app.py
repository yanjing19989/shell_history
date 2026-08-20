from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import webbrowser
import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

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


def shells_data():
    return {"shells": [{"name": a.name, "label": a.label, "path": str(a.detect()) if a.detect() else None, "available": bool(a.detect())} for a in ADAPTERS.values()]}


def history_data(query):
    name = query.get("shell", [""])[0]
    adapter = ADAPTERS.get(name)
    if not adapter:
        return {"error": "unknown shell"}, 400
    path = Path(query.get("path", [None])[0] or adapter.detect() or "")
    if not path.is_file():
        return {"error": "history file not found", "shell": name}, 404
    try:
        records, encoding = adapter.parse(path)
        result = payload(records)
        result.update({"shell": name, "path": str(path), "encoding": encoding})
        return result, 200
    except OSError as exc:
        return {"error": str(exc)}, 400


def records_from_json(items, shell, path):
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("command"), str):
            continue
        out.append(Record(str(item.get("id", "")), item["command"], item.get("timestamp"), shell, str(path), int(item.get("line_number", 0))))
    return out


def preview_data(body):
    shell, path = body.get("shell"), body.get("path")
    adapter = ADAPTERS.get(shell)
    if not adapter or not path:
        return {"error": "shell and path are required"}, 400
    records = records_from_json(body.get("records", []), shell, path)
    return {"path": path, "shell": shell, "count": len(records), "stats": stats(records), "content": adapter.serialize(records)}, 200


def save_data(body):
    shell, path_value = body.get("shell"), body.get("path")
    adapter = ADAPTERS.get(shell)
    if not adapter or not path_value:
        return {"error": "shell and path are required"}, 400
    path = Path(path_value).expanduser()
    if not path.is_file():
        return {"error": "history file not found"}, 404
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
            return {"ok": True, "backup": str(backup), "path": str(path), "stats": stats(records)}, 200
        except OSError as exc:
            return {"error": str(exc)}, 500


BASE_DIR = Path(__file__).resolve().parent


class HistoryHandler(BaseHTTPRequestHandler):
    server_version = "ShellHistory/1.0"

    def log_message(self, format, *args):
        # Keep the local tool's console quiet except for errors raised by handlers.
        return

    def send_json(self, data, status=HTTPStatus.OK):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path, content_type):
        try:
            raw = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlsplit(self.path)
        route = unquote(parsed.path)
        try:
            if route == "/":
                return self.send_file(BASE_DIR / "templates" / "index.html", "text/html; charset=utf-8")
            if route == "/api/shells":
                return self.send_json(shells_data())
            if route == "/api/history":
                data, status = history_data(parse_qs(parsed.query))
                return self.send_json(data, status)
            if route.startswith("/static/"):
                static_root = (BASE_DIR / "static").resolve()
                file_path = (static_root / route.removeprefix("/static/")).resolve()
                if static_root not in file_path.parents or not file_path.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return self.send_file(file_path, guess_type(str(file_path))[0] or "application/octet-stream")
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        route = unquote(urlsplit(self.path).path)
        length = int(self.headers.get("Content-Length", "0"))
        if length > 50 * 1024 * 1024:
            return self.send_json({"error": "request body too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self.send_json({"error": "invalid JSON body"}, HTTPStatus.BAD_REQUEST)
        try:
            if route == "/api/history/preview":
                data, status = preview_data(body)
            elif route == "/api/history/save":
                data, status = save_data(body)
            else:
                return self.send_error(HTTPStatus.NOT_FOUND)
            self.send_json(data, status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def open_browser(host, port):
    webbrowser.open("http://{}:{}".format(host, port))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="shell_history")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7000, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        threading.Timer(0.8, lambda: open_browser(args.host, args.port)).start()
    print("Starting ShellHistory server at http://{}:{}".format(args.host, args.port))
    server = ThreadingHTTPServer((args.host, args.port), HistoryHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
