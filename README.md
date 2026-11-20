# <img src="favicon.ico" width="32" height="32" alt=""> Shell History

一个轻量、无需第三方依赖的本机 Shell 历史记录 Web 管理器。

项目使用 Python 标准库提供本地 HTTP 服务，通过浏览器管理 Bash、Zsh、PowerShell 等 Shell 的历史命令。支持搜索、排序、批量选择、复制、删除、去重以及安全保存。

## 功能

- **多 Shell 支持**
  - Bash
  - Zsh
  - PowerShell / PSReadLine
  - Command Prompt（支持通过环境变量指定历史文件）
- **自动检测历史文件**
  - 根据当前用户环境和常见路径自动查找历史文件。
  - 也可以手动输入历史文件的完整路径。
- **命令搜索**
  - 普通文本搜索。
  - 支持正则表达式，例如 `/docker\s+run/i`。
- **两种查看模式**
  - **时间模式**：逐条显示历史记录。
  - **去重模式**：按照命令统计出现次数。
- **排序**
  - 行号
  - 命令
  - 时间戳
  - 去重模式下还可以按照数量排序。
- **批量操作**
  - 全选
  - 反选
  - Shift 连选
  - 复制选中命令
  - 删除选中记录
  - 对选中记录去重，并保留每个命令最近一次记录
- **安全保存**
  - 保存前自动创建 `.bak-YYYYMMDD-HHMMSS` 备份。
  - 使用临时文件写入，并通过 `os.replace()` 原子替换原文件，降低写入过程中损坏历史文件的风险。
- **主题**
  - 自动跟随系统
  - 浅色
  - 深色
- **零第三方依赖**
  - 后端仅使用 Python 标准库。
  - 前端为原生 HTML / CSS / JavaScript。

## 项目结构

```text
shell_history/
├── app.py                 # 后端 HTTP 服务、Shell 历史解析及保存逻辑
├── templates/
│   └── index.html         # Web 页面
└── static/
    ├── app.js             # 前端交互逻辑
    └── style.css          # 页面样式
```

## 环境要求

建议使用：

- Python 3.9+
- 支持现代 JavaScript 的浏览器

项目没有 `pip` 第三方依赖，因此无需执行 `pip install`。

> 注意：当前代码使用了 `Path.removeprefix()`，因此实际运行环境建议使用 Python 3.9 或更高版本。如果需要兼容更老的 Python 3 版本，需要将该调用改写为传统字符串切片方式。

## 快速开始

进入项目目录：

```bash
cd shell_history
```

直接启动：

```bash
python3 app.py
```

默认监听：

```text
http://127.0.0.1:7000
```

启动后程序会尝试自动打开浏览器。

### 不自动打开浏览器

```bash
python3 app.py --no-browser
```

然后手动访问：

```text
http://127.0.0.1:7000
```

### 修改监听地址和端口

```bash
python3 app.py --host 127.0.0.1 --port 8080
```

例如允许局域网访问：

```bash
python3 app.py --host 0.0.0.0 --port 8080
```

如果绑定到 `0.0.0.0`，请注意该服务没有实现用户认证和 HTTPS，不建议直接暴露到公网。

## 使用方法

### 1. 选择 Shell

页面顶部可以选择：

- Bash
- Zsh
- PowerShell
- Command Prompt

如果程序检测到了默认历史文件，会自动填充路径。

也可以手动输入历史文件路径，例如：

```text
~/.bash_history
```

或：

```text
/home/user/.zsh_history
```

然后点击 **加载**。

### 2. 搜索命令

搜索框支持普通文本和正则表达式。

普通搜索：

```text
docker
```

正则搜索：

```text
/^git\s+(pull|push)/i
```

正则表达式格式：

```text
/表达式/flags
```

例如：

```text
/ssh\s+.*@/i
```

如果正则表达式无效，页面会显示错误信息。

### 3. 删除命令

勾选需要删除的记录，然后点击 **删除**。

删除操作只会修改浏览器当前内存中的记录，**不会立即写入历史文件**。

确认无误后点击 **保存** 才会修改原文件。

### 4. 命令去重

点击 **去重模式**可以查看每条唯一命令的出现次数。

也可以在时间模式下选中若干记录，然后点击 **仅保留一个**。

该操作：

- 只处理选中的记录；
- 相同命令只保留一条；
- 保留该命令**最近一次**出现的记录；
- 同样需要点击 **保存** 才会写入磁盘。

### 5. 复制命令

勾选记录后点击 **复制**，选中的命令会按照历史记录顺序复制到系统剪贴板，每条命令占一行。

## Shell 历史格式

### Bash

默认查找：

```text
~/.bash_history
```

如果设置了 `HISTFILE`，优先使用该环境变量指定的文件。

Bash 历史按照普通逐行文本处理。

### Zsh

默认查找：

```text
~/.zsh_history
```

如果设置了 `HISTFILE`，优先使用该环境变量指定的文件。

支持常见的 Zsh extended history 格式，例如：

```text
: 1724000000:0;git status
```

读取时会将 Unix 时间戳转换为 ISO 8601 时间。

保存时，如果记录存在时间戳，会重新生成类似：

```text
: 1724000000:0;git status
```

的格式。

### PowerShell

优先查找：

```text
%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt
```

同时兼容常见的用户目录路径。

PowerShell 历史文件按照逐行命令处理。

### Command Prompt

`cmd.exe` 本身没有统一的持久化历史文件，因此项目不会假定固定路径。

可以通过以下环境变量指定历史文件：

```text
CMD_HISTORY_FILE
```

或：

```text
CMDER_HISTORY
```

例如 Linux/macOS：

```bash
export CMD_HISTORY_FILE="$HOME/.cmd_history"
python3 app.py
```

## 编码处理

读取历史文件时会依次尝试常见编码：

```text
utf-8-sig
utf-16
utf-16-le
utf-16-be
当前终端设备编码
cp1252
```

如果仍然无法解码，则使用 UTF-8 replacement 模式读取，避免因为单个异常字节导致整个文件无法加载。

## 保存机制

保存历史文件时执行以下流程：

```text
原历史文件
    │
    ├── 创建 .bak-时间戳 备份
    │
    ├── 创建同目录临时文件
    │
    ├── 写入新内容
    │
    ├── flush + fsync
    │
    └── os.replace() 原子替换原文件
```

例如：

```text
.bash_history
.bash_history.bak-20260820-221500
```

因此如果误删命令，可以从对应的 `.bak-*` 文件恢复。

## HTTP API

后端同时提供简单的 JSON API。

### 获取 Shell 列表

```http
GET /api/shells
```

返回示例：

```json
{
  "shells": [
    {
      "name": "bash",
      "label": "Bash",
      "path": "/home/user/.bash_history",
      "available": true
    }
  ]
}
```

### 读取历史

```http
GET /api/history?shell=bash&path=/home/user/.bash_history
```

返回记录、统计信息以及实际读取编码。

### 预览保存内容

```http
POST /api/history/preview
Content-Type: application/json
```

请求体：

```json
{
  "shell": "bash",
  "path": "/home/user/.bash_history",
  "records": []
}
```

接口不会修改文件，只返回序列化后的历史内容。

### 保存历史

```http
POST /api/history/save
Content-Type: application/json
```

请求体：

```json
{
  "shell": "bash",
  "path": "/home/user/.bash_history",
  "records": []
}
```

保存成功后会返回备份文件路径和统计信息。

## 安全注意事项

这是一个面向**本机使用**的管理工具。

默认只监听：

```text
127.0.0.1
```

如果使用：

```bash
python3 app.py --host 0.0.0.0
```

则局域网或其他能够访问该端口的主机可能访问该服务。

由于历史命令通常可能包含：

- 密码
- Token
- API Key
- 内网地址
- 文件路径
- 服务器信息

因此不建议将服务直接暴露到公网。

同时，保存操作具有修改本机历史文件的权限，请在执行删除、去重和保存前确认目标文件路径。

## 设计说明

后端采用 Python 标准库：

```text
http.server
threading
pathlib
json
argparse
datetime
shutil
tempfile
```

通过 `Adapter` 抽象不同 Shell 的历史格式：

```text
Adapter
├── BashAdapter
├── ZshAdapter
├── PowerShellAdapter
└── CmdAdapter
```

如果以后需要支持新的 Shell，可以继承 `Adapter` 并实现：

- `name`
- `label`
- `candidates()`
- `parse_text()`（如果历史格式特殊）
- `serialize()`（如果保存格式特殊）

然后将 Adapter 加入 `ADAPTERS` 即可。

## 常见问题

### 为什么点击“选择文件”不能直接选择历史文件？

浏览器的安全机制不会把用户选择的本地文件完整路径直接提供给普通网页 JavaScript。

因此当前页面的“选择文件”按钮主要用于提示用户输入完整路径；实际读取文件由本机 Python 后端完成。

### 删除后文件没有立即变化？

这是设计如此。

删除、去重等操作先在浏览器内存中进行，只有点击 **保存** 后才会修改实际历史文件。

### 保存失败怎么办？

首先检查：

1. 当前用户是否拥有历史文件的写权限；
2. 文件所在目录是否允许创建临时文件；
3. 历史文件是否被其他程序锁定；
4. 输入的路径是否正确。

保存前程序会创建备份文件，因此可以优先检查对应的 `.bak-*` 文件。
