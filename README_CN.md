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

**ClawForge** — OpenClaw 插件开发脚手架与调试工具链

[![PyPI version](https://img.shields.io/pypi/v/clawforge?color=brightgreen)](https://pypi.org/project/clawforge/)
[![Python](https://img.shields.io/badge/python-3.9%20|%203.10%20|%203.11%20|%203.12-blue)](https://www.python.org/)
[![CI](https://github.com/hidearmoon/openclaw-clawforge/actions/workflows/ci.yml/badge.svg)](https://github.com/hidearmoon/openclaw-clawforge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/hidearmoon/openclaw-clawforge/pulls)

</div>

---

> **ClawForge** 是 [OpenClaw](https://github.com/openclaw) 插件开发者的官方工具链。一条命令生成生产级插件骨架，热重载本地调试，发布前验证兼容性——全部通过一个 CLI 完成。

## 核心功能

- 🚀 **`clawforge init`** — 一键生成全部 4 种 OpenClaw 插件类型（`tool`、`channel`、`memory`、`provider`），包含清单文件、接口骨架、测试桩和 README。
- 🔥 **`clawforge dev`** — 本地热重载沙箱。修改插件代码，立即看到变化，无需重启。内置 HTTP 控制接口（`localhost:9621`）。
- 🧪 **`clawforge test`** — 兼容性测试套件。在发布前验证清单完整性、接口合规性（`init`/`run`/`shutdown`）、目录结构和依赖声明。
- 🎨 **丰富的终端界面** — 彩色输出、结构化表格、进度反馈，而不只是纯文本日志。
- 📦 **CI 友好** — `clawforge test --json` 输出机器可读格式，可直接通过管道传给 `jq`。

---

## 快速开始

> 30 秒内跑起来。

```bash
# 安装
pip install clawforge

# 生成一个 tool 类型插件
clawforge init --type tool --name my-tool

# 进入生成目录
cd my-tool

# 启动热重载沙箱
clawforge dev .
```

沙箱已在 **`http://localhost:9621`** 启动。编辑 `my_tool.py`，每次保存后插件自动重载。

```bash
# 通过 HTTP 调用你的插件
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"input": "你好世界"}'
```

---

## 安装

```bash
# 从 PyPI 安装（推荐）
pip install clawforge

# 从源码安装
git clone https://github.com/hidearmoon/openclaw-clawforge.git
cd openclaw-clawforge
pip install -e ".[dev]"
```

**系统要求：** Python ≥ 3.9

---

## 命令详解

### `clawforge init`

生成一个新的 OpenClaw 插件，支持交互式或全非交互式两种模式。

```bash
# 交互式（有引导提示）
clawforge init

# 非交互式（直接传入所有参数）
clawforge init --type tool     --name my-tool       --description "我的工具"  --author 张三
clawforge init --type channel  --name telegram-bot  --author 李四
clawforge init --type memory   --name sqlite-store
clawforge init --type provider --name openrouter
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--type` | 交互提示 | 插件类型：`tool` `channel` `memory` `provider` |
| `--name` | 交互提示 | 插件名（kebab-case 格式） |
| `--description` | `""` | 插件简介（显示在市场中） |
| `--author` | `""` | 作者名 |
| `--version` | `0.1.0` | 初始语义化版本号 |
| `--output-dir`, `-o` | `./<name>` | 自定义输出路径 |
| `--force`, `-f` | 关闭 | 覆盖已存在的文件 |

**生成的目录结构：**

```
my-tool/
├── openclaw.plugin.json   ← OpenClaw 插件清单
├── my_tool.py             ← IPlugin 接口骨架实现
├── test_my_tool.py        ← pytest 测试桩（可直接运行）
├── README.md              ← 插件专属 README
└── .gitignore
```

---

### `clawforge dev`

启动本地沙箱，支持热重载和 HTTP 手动调用接口。

```bash
clawforge dev .                      # 监听当前目录
clawforge dev ./my-tool              # 监听指定插件目录
clawforge dev ./my-tool --port 9000  # 自定义端口
clawforge dev . --no-watch           # 只加载一次，关闭文件监听
clawforge dev . --no-server          # 不启动 HTTP 服务，只加载并监听
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PLUGIN_DIR` | `.` | 包含 `openclaw.plugin.json` 的目录 |
| `--port`, `-p` | `9621` | HTTP 服务端口 |
| `--no-watch` | 关闭 | 禁用热重载文件监听 |
| `--no-server` | 关闭 | 不启动 HTTP 服务 |

**HTTP 控制接口：**

| 方法 | 路由 | 说明 |
|------|------|------|
| `GET` | `/` | 健康检查 + 插件列表 |
| `GET` | `/plugins` | 所有已注册插件及元数据 |
| `POST` | `/run/{name}` | 调用 `plugin.run(payload)` |
| `POST` | `/reload/{name}` | 手动触发插件重载 |
| `GET` | `/status` | 纯文本注册表状态 |

```bash
# 调用插件
curl -X POST http://localhost:9621/run/my-tool \
     -H "Content-Type: application/json" \
     -d '{"key": "value"}'

# 手动触发重载
curl -X POST http://localhost:9621/reload/my-tool

# 查看已加载插件
curl http://localhost:9621/status
```

---

### `clawforge test`

对插件目录运行完整兼容性检查套件。建议在执行 `clawforge publish` 前先跑一遍。

```bash
clawforge test .               # 检查当前目录
clawforge test ./my-tool       # 检查指定插件
clawforge test . --json        # 输出机器可读 JSON（适用于 CI）
clawforge test . --json | jq .summary
```

**检查项说明：**

| # | 分类 | 验证内容 |
|---|------|---------|
| 1 | **清单验证** | `openclaw.plugin.json` 存在、合法 JSON、必填字段完整、语义化版本格式、`模块:类名` 入口格式、入口文件存在 |
| 2 | **接口合规** | 插件类可导入、`init(config)` / `run(payload)` / `shutdown()` 全部存在且签名正确 |
| 3 | **目录结构** | README 文件存在、`.gitignore` 存在、测试文件存在 |
| 4 | **依赖声明** | `requirements.txt` 或 `pyproject.toml` 存在且可解析 |

**退出码：**

| 退出码 | 含义 |
|--------|------|
| `0` | 全部检查通过（警告不阻塞） |
| `1` | 有一项或多项检查**失败** |

**JSON 输出格式（用于 CI 脚本）：**

```bash
clawforge test . --json | jq .
# {
#   "plugin_dir": "/abs/path/my-tool",
#   "results": [...],
#   "summary": { "pass": 14, "fail": 0, "warn": 2 }
# }
```

---

## 插件类型说明

| 类型 | 适用场景 | 示例 |
|------|---------|------|
| `tool` | 为 OpenClaw 添加自定义能力 | 网页搜索、计算器、代码执行器 |
| `channel` | 接入新的输入/输出渠道 | Telegram Bot、Slack Webhook、Discord |
| `memory` | 自定义记忆后端 | SQLite、Redis、向量数据库 |
| `provider` | 新的 LLM API 适配器 | OpenRouter、Replicate、本地 Ollama |

---

## 插件接口规范

每个插件需实现三个生命周期方法：

```python
from clawforge.sandbox import IPlugin

class MyPlugin(IPlugin):
    def init(self, config: dict) -> None:
        """加载后调用一次。在此初始化配置、创建客户端。"""
        self.timeout = config.get("timeout", 10)

    def run(self, payload: dict) -> Any:
        """每次调用时执行。返回任意可 JSON 序列化的值。"""
        return {"result": f"已处理: {payload}"}

    def shutdown(self) -> None:
        """卸载前调用。在此关闭连接、刷新缓冲区。"""
        pass
```

---

## 插件清单（openclaw.plugin.json）

`openclaw.plugin.json` 是插件身份和元数据的唯一来源：

```json
{
  "name": "my-tool",
  "version": "0.1.0",
  "description": "我的自定义工具插件",
  "author": "张三",
  "type": "tool",
  "engine": ">=0.1.0",
  "entry": "my_tool:MyTool",
  "permissions": ["network"],
  "config": {
    "timeout": 10
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 插件名（kebab-case） |
| `version` | string | ✅ | 语义化版本（`x.y.z`） |
| `type` | string | ✅ | `tool` / `channel` / `memory` / `provider` |
| `engine` | string | ✅ | 兼容的 OpenClaw 版本范围（如 `>=0.1.0`） |
| `entry` | string | ✅ | `模块名:类名`（如 `my_tool:MyTool`） |
| `description` | string | — | 插件简介 |
| `author` | string | — | 作者名 |
| `permissions` | array | — | 所需权限：`network`、`fs`、`env` |
| `config` | object | — | 插件默认配置项 |

---

## 配置说明

ClawForge 本身没有配置文件——所有选项通过 CLI 参数传入。插件自身的运行时配置放在 `openclaw.plugin.json` 的 `config` 字段中，沙箱加载时会将其传给 `plugin.init(config)`。

---

## 参与贡献

欢迎 Issue 和 PR！重大变更请先开 Issue 讨论。

```bash
# 克隆并配置开发环境
git clone https://github.com/hidearmoon/openclaw-clawforge.git
cd openclaw-clawforge
pip install -e ".[dev]"

# 运行测试套件
pytest --tb=short -q

# 针对特定 Python 版本运行
python3.11 -m pytest --tb=short
```

**提交 PR 前请确认：**
- 全部 62+ 个测试通过：`pytest`
- 新功能需附带对应测试
- 代码风格与现有代码保持一致

---

## 许可证

[MIT](LICENSE) © 2024 OpenClaw Labs
