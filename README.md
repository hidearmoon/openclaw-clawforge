<!-- Language Switch | 语言切换 -->
<p align="right">
  <a href="README.md">English</a> · <a href="README_CN.md">中文</a>
</p>

<div align="center">

```
   ___  _                 ___
  / __\| |  __ _ __  __ / __\ ___  _ __  __ _  ___
 / /   | | / _` |\ \/ // /   / _ \| '__|/ _` |/ _ \
/ /___ | || (_| | >  </ /___| (_) | |  | (_| |  __/
\____/ |_| \__,_|/_/\_\\____/ \___/|_|   \__, |\___|
                                          |___/
```

**ClawForge** — OpenClaw Plugin Development Scaffold & Toolchain

[![PyPI version](https://img.shields.io/pypi/v/clawforge?color=brightgreen)](https://pypi.org/project/clawforge/)
[![Python](https://img.shields.io/badge/python-3.9%20|%203.10%20|%203.11%20|%203.12-blue)](https://www.python.org/)
[![CI](https://github.com/hidearmoon/openclaw-clawforge/actions/workflows/ci.yml/badge.svg)](https://github.com/hidearmoon/openclaw-clawforge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/hidearmoon/openclaw-clawforge/pulls)

</div>

---

> **ClawForge** is the official developer toolchain for [OpenClaw](https://github.com/openclaw) plugin authors. Scaffold a production-ready plugin in seconds, iterate with hot-reload, and validate compatibility before publishing — all from one CLI.

## Features

- 🚀 **`clawforge init`** — One-command scaffold for all 4 OpenClaw plugin types (`tool`, `channel`, `memory`, `provider`). Generates manifest, interface skeleton, test stubs, and README.
- 🔥 **`clawforge dev`** — Local hot-reload sandbox. Edit your plugin and watch it reload instantly — no server restart needed. Includes an HTTP control API at `localhost:9621`.
- 🧪 **`clawforge test`** — Compatibility test suite. Validates manifest completeness, interface compliance (`init`/`run`/`shutdown`), directory structure, and dependency listings before you publish.
- 🎨 **Rich terminal UI** — Color-coded output, structured tables, progress feedback — not just plain text.
- 📦 **CI-ready** — `--json` flag on `clawforge test` for machine-readable output, pipeable to `jq`.

---

## Quick Start

> Get a plugin running in under 30 seconds.

```bash
# Install (from source — PyPI release coming soon, see Installation section)
git clone https://github.com/hidearmoon/openclaw-clawforge.git
cd openclaw-clawforge
pip install -e .

# Scaffold a new "tool" plugin
clawforge init --type tool --name my-tool

# Enter the generated directory
cd my-tool

# Start the hot-reload sandbox
clawforge dev .
```

The sandbox is now live at **`http://localhost:9621`**. Edit `my_tool.py` — the plugin reloads automatically on every save.

```bash
# Invoke your plugin via HTTP
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"input": "hello world"}'
```

---

## Installation

```bash
# From source (current method — PyPI release pending)
git clone https://github.com/hidearmoon/openclaw-clawforge.git
cd openclaw-clawforge
pip install -e ".[dev]"

# From PyPI (coming soon — will switch to this once published)
# pip install clawforge
```

**Requirements:** Python ≥ 3.9

---

## Commands

### `clawforge init`

Scaffold a new OpenClaw plugin — interactively or fully non-interactive.

```bash
# Interactive (guided prompts)
clawforge init

# Non-interactive (all flags provided)
clawforge init --type tool     --name my-tool       --description "My tool"  --author Alice
clawforge init --type channel  --name telegram-bot  --author Bob
clawforge init --type memory   --name sqlite-store
clawforge init --type provider --name openrouter
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--type` | prompted | Plugin type: `tool` `channel` `memory` `provider` |
| `--name` | prompted | Plugin name in kebab-case |
| `--description` | `""` | Short description shown in the marketplace |
| `--author` | `""` | Author name |
| `--version` | `0.1.0` | Initial semantic version |
| `--output-dir`, `-o` | `./<name>` | Custom output path |
| `--force`, `-f` | off | Overwrite files that already exist |

**Generated project layout:**

```
my-tool/
├── openclaw.plugin.json   ← OpenClaw plugin manifest
├── my_tool.py             ← IPlugin implementation skeleton
├── test_my_tool.py        ← pytest test stubs (ready to run)
├── README.md              ← Plugin-specific README
└── .gitignore
```

---

### `clawforge dev`

Start a local sandbox with hot-reload and an HTTP API for manual plugin invocation.

```bash
clawforge dev .                      # watch current directory
clawforge dev ./my-tool              # watch specific plugin directory
clawforge dev ./my-tool --port 9000  # custom port
clawforge dev . --no-watch           # load once, disable file watcher
clawforge dev . --no-server          # no HTTP API, just load + watch
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `PLUGIN_DIR` | `.` | Directory containing `openclaw.plugin.json` |
| `--port`, `-p` | `9621` | HTTP API port |
| `--no-watch` | off | Disable hot-reload file watcher |
| `--no-server` | off | Skip HTTP server entirely |

**HTTP Control API:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check + plugin list |
| `GET` | `/plugins` | All registered plugins with metadata |
| `POST` | `/run/{name}` | Invoke `plugin.run(payload)` |
| `POST` | `/reload/{name}` | Manually trigger plugin reload |
| `GET` | `/status` | Plain-text registry status |

```bash
# Invoke plugin
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"key": "value"}'

# Trigger manual reload
curl -X POST http://localhost:9621/reload/my-tool

# Check what's loaded
curl http://localhost:9621/status
```

---

### `clawforge test`

Run a full compatibility check suite against a plugin directory. Use this before `clawforge publish`.

```bash
clawforge test .               # check current directory
clawforge test ./my-tool       # check a specific plugin
clawforge test . --json        # machine-readable output (for CI)
clawforge test . --json | jq .summary
```

**Checks performed:**

| # | Category | What it validates |
|---|----------|-------------------|
| 1 | **Manifest** | `openclaw.plugin.json` exists, valid JSON, required fields present, semver version, `module:ClassName` entry format, entry file exists |
| 2 | **Interface** | Plugin class importable, `init(config)` / `run(payload)` / `shutdown()` all present with correct signatures |
| 3 | **Structure** | README file present, `.gitignore` present, test files present |
| 4 | **Dependencies** | `requirements.txt` or `pyproject.toml` present and parseable |

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All checks passed (warnings are non-blocking) |
| `1` | One or more checks **failed** |

**JSON output (for CI scripting):**

```bash
clawforge test . --json | jq .
# {
#   "plugin_dir": "/abs/path/my-tool",
#   "results": [...],
#   "summary": { "pass": 14, "fail": 0, "warn": 2 }
# }
```

---

## Plugin Types

| Type | Use Case | Example |
|------|----------|---------|
| `tool` | Extend OpenClaw with custom capabilities | web search, calculator, code runner |
| `channel` | Add new input/output channels | Telegram bot, Slack webhook, Discord |
| `memory` | Custom memory backends | SQLite, Redis, vector database |
| `provider` | New LLM API adapters | OpenRouter, Replicate, local Ollama |

---

## Plugin Interface

Every plugin implements three lifecycle methods:

```python
from clawforge.sandbox import IPlugin

class MyPlugin(IPlugin):
    def init(self, config: dict) -> None:
        """Called once on load. Validate config and create clients here."""
        self.timeout = config.get("timeout", 10)

    def run(self, payload: dict) -> Any:
        """Called on every invocation. Return any JSON-serializable value."""
        return {"result": f"processed: {payload}"}

    def shutdown(self) -> None:
        """Called before unload. Close connections, flush buffers."""
        pass
```

---

## Plugin Manifest

`openclaw.plugin.json` is the single source of truth for plugin identity and metadata:

```json
{
  "name": "my-tool",
  "version": "0.1.0",
  "description": "My custom tool plugin",
  "author": "Alice",
  "type": "tool",
  "engine": ">=0.1.0",
  "entry": "my_tool:MyTool",
  "permissions": ["network"],
  "config": {
    "timeout": 10
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Plugin name (kebab-case) |
| `version` | string | ✅ | Semantic version (`x.y.z`) |
| `type` | string | ✅ | `tool` / `channel` / `memory` / `provider` |
| `engine` | string | ✅ | Compatible OpenClaw version range (e.g. `>=0.1.0`) |
| `entry` | string | ✅ | `module:ClassName` (e.g. `my_tool:MyTool`) |
| `description` | string | — | Short description |
| `author` | string | — | Author name |
| `permissions` | array | — | Required permissions: `network`, `fs`, `env` |
| `config` | object | — | Default configuration values |

---

## Configuration

ClawForge itself has no configuration file — all options are passed as CLI flags. The plugin's own runtime config lives in the `config` block of `openclaw.plugin.json` and is passed to `plugin.init(config)` when the sandbox loads.

---

## Contributing

Contributions are welcome! Please open an issue first for major changes.

```bash
# Clone and set up dev environment
git clone https://github.com/hidearmoon/openclaw-clawforge.git
cd openclaw-clawforge
pip install -e ".[dev]"

# Run the test suite
pytest --tb=short -q

# Run against a specific Python version
python3.11 -m pytest --tb=short
```

**Before opening a PR:**
- All 62+ tests must pass: `pytest`
- New features need corresponding tests
- Follow existing code style (no formatter required, just match the surrounding code)

---

## License

[MIT](LICENSE) © 2024 OpenClaw Labs
