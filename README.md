# ClawForge

**OpenClaw Plugin Development Scaffold & Hot-Reload Dev Sandbox**

> 为 OpenClaw 插件开发者打造的脚手架工具：一键生成插件模板、本地热重载沙箱调试、HTTP 控制接口。

[![PyPI](https://img.shields.io/pypi/v/clawforge)](https://pypi.org/project/clawforge/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## English

### What is ClawForge?

ClawForge is a developer toolkit for building [OpenClaw](https://github.com/openclaw) plugins. It fills the gap between `claw-init` (general project scaffold) and a full plugin release:

| Feature | Description |
|---------|-------------|
| `clawforge init` | Scaffold any of 4 plugin types with manifest, interface skeleton, tests, and README |
| `clawforge dev` | Local sandbox with hot-reload — edit & see changes instantly, no restart needed |
| HTTP control API | Invoke `plugin.run()` via `curl` / Postman at `http://localhost:9621` |

**Plugin types supported:** `tool` · `channel` · `memory` · `provider`

### Quick Start (30 seconds)

```bash
# 1. Install
pip install clawforge

# 2. Scaffold a new tool plugin
clawforge init --type tool --name my-tool

# 3. Enter the generated directory
cd my-tool

# 4. Start hot-reload sandbox
clawforge dev .
```

The sandbox starts at `http://localhost:9621`. Edit `my_tool.py` and the plugin reloads automatically.

### Installation

```bash
pip install clawforge
# or from source:
git clone https://github.com/hidearmoon/clawforge
cd clawforge
pip install -e .
```

Requirements: Python ≥ 3.9

### Commands

#### `clawforge init`

Scaffold a new plugin interactively or with flags:

```bash
# Interactive mode (guided prompts)
clawforge init

# Non-interactive mode
clawforge init --type tool     --name my-tool --description "My tool" --author Alice
clawforge init --type channel  --name tg-bot
clawforge init --type memory   --name sqlite-memory
clawforge init --type provider --name openrouter-provider
```

**Options:**

| Option | Description |
|--------|-------------|
| `--type` | Plugin type: `tool`, `channel`, `memory`, `provider` |
| `--name` | Plugin name (kebab-case) |
| `--description` | Short description |
| `--author` | Author name |
| `--version` | Initial version (default: `0.1.0`) |
| `--output-dir`, `-o` | Output directory (default: `./<name>`) |
| `--force`, `-f` | Overwrite existing files |

**Generated files:**

```
my-tool/
├── openclaw.plugin.json   ← plugin manifest
├── my_tool.py             ← IPlugin implementation skeleton
├── test_my_tool.py        ← pytest test stubs
├── README.md
└── .gitignore
```

#### `clawforge dev`

Start a local sandbox for iterative development:

```bash
clawforge dev .                  # watch current directory
clawforge dev ./my-tool --port 9000
clawforge dev . --no-watch       # disable auto-reload
clawforge dev . --no-server      # no HTTP API, just load + watch
```

**Options:**

| Option | Description |
|--------|-------------|
| `PLUGIN_DIR` | Directory with `openclaw.plugin.json` (default: `.`) |
| `--port`, `-p` | HTTP API port (default: `9621`) |
| `--no-watch` | Disable hot-reload file watcher |
| `--no-server` | Skip HTTP server |

**HTTP API (port 9621):**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health + plugin list |
| `GET` | `/plugins` | All registered plugins |
| `POST` | `/run/{name}` | Invoke `plugin.run(payload)` |
| `POST` | `/reload/{name}` | Manually trigger reload |
| `GET` | `/status` | Plain-text registry status |

```bash
# Invoke your plugin
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"input": "hello world"}'

# Manual reload
curl -X POST http://localhost:9621/reload/my-tool
```

### Plugin Interface

All plugins implement three lifecycle methods:

```python
class MyPlugin(IPlugin):
    def init(self, config: dict) -> None:
        """Called once on load — validate config, create clients."""

    def run(self, payload: dict) -> Any:
        """Main invocation — called on each request."""

    def shutdown(self) -> None:
        """Called before unload — close connections, flush data."""
```

### Plugin Manifest (`openclaw.plugin.json`)

```json
{
  "name": "my-tool",
  "version": "0.1.0",
  "description": "My tool plugin",
  "author": "Alice",
  "type": "tool",
  "engine": ">=0.1.0",
  "entry": "my_tool:MyTool",
  "permissions": ["network"],
  "config": { "timeout": 10 }
}
```

---

## 中文文档

### 什么是 ClawForge？

ClawForge 是专为 [OpenClaw](https://github.com/openclaw) 插件开发者打造的脚手架工具，填补了通用脚手架 `claw-init` 和插件正式发布之间的空白：

| 功能 | 说明 |
|------|------|
| `clawforge init` | 一键生成 4 种插件类型的清单文件、接口骨架、测试桩和 README |
| `clawforge dev` | 本地热重载沙箱——修改代码立即生效，无需重启 |
| HTTP 控制接口 | 通过 `curl` / Postman 在 `http://localhost:9621` 手动触发插件 `run()` |

**支持的插件类型：** `tool` · `channel` · `memory` · `provider`

### 快速开始（30 秒跑起来）

```bash
# 1. 安装
pip install clawforge

# 2. 生成一个 tool 类型插件
clawforge init --type tool --name my-tool

# 3. 进入生成目录
cd my-tool

# 4. 启动热重载沙箱
clawforge dev .
```

沙箱启动在 `http://localhost:9621`。编辑 `my_tool.py`，插件会自动重新加载。

### `clawforge init` 详解

```bash
# 交互式模式（有引导提示）
clawforge init

# 非交互式模式
clawforge init --type tool --name my-tool --description "我的工具" --author 张三
```

生成的文件：

```
my-tool/
├── openclaw.plugin.json   ← 插件清单
├── my_tool.py             ← IPlugin 接口骨架实现
├── test_my_tool.py        ← pytest 测试桩
├── README.md
└── .gitignore
```

### `clawforge dev` 详解

```bash
clawforge dev .               # 监听当前目录
clawforge dev ./my-tool --port 9000
clawforge dev . --no-watch    # 关闭自动重载
```

**HTTP 控制接口（端口 9621）：**

```bash
# 调用插件 run()
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"input": "你好"}'

# 手动重载
curl -X POST http://localhost:9621/reload/my-tool

# 查看插件状态
curl http://localhost:9621/status
```

### 插件接口规范

OpenClaw 插件实现三个生命周期方法：

```python
class MyPlugin(IPlugin):
    def init(self, config: dict) -> None:
        """加载后调用一次——初始化配置、创建客户端"""

    def run(self, payload: dict) -> Any:
        """主调用入口——每次请求都会调用"""

    def shutdown(self) -> None:
        """卸载前调用——关闭连接、刷新缓冲区"""
```

### 插件清单（openclaw.plugin.json）字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 插件名（kebab-case） |
| `version` | string | 语义化版本 |
| `type` | string | `tool` / `channel` / `memory` / `provider` |
| `engine` | string | 兼容的 OpenClaw 版本范围（如 `>=0.1.0`） |
| `entry` | string | `模块名:类名`（如 `my_tool:MyTool`） |
| `permissions` | array | 所需权限声明（如 `network`、`fs`） |
| `config` | object | 插件默认配置 |

---

## Contributing / 贡献

Issues and PRs welcome at [github.com/hidearmoon/clawforge](https://github.com/hidearmoon/clawforge).

## License

MIT © OpenClaw Labs
