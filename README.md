# OpenCode Go Switch

本地 AI 模型代理切换器，将 Codex (Responses API) 和 Claude Code (Anthropic Messages) 的请求透明转发到 OpenCode Go 上游，支持热切换模型。

## 架构

```
Codex (Responses API) ──→ /v1/responses  ──→ /v1/chat/completions ──→ OpenCode Go
                               │
Claude Code (Messages)  ──→ /v1/messages   ──→ /v1/messages        ──→ OpenCode Go
                               │
                     Web Console :7878 (模型切换)
```

- **流式转换**: Codex 的 Responses SSE 事件 ↔ Chat Completions SSE chunks，逐块实时转译
- **Anthropic 直通**: Claude Code 的 Messages API 字节级透传，零缓冲延迟
- **模型强制覆盖**: 代理忽略客户端传的 model，始终使用控制台选择的模型

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp config.example.json config.json
# 编辑 config.json，填入你的 OpenCode Go API Key

# 3. 启动
python server.py
```

打开 http://127.0.0.1:7878 即可切换模型。

## 客户端配置

### Codex

`~/.codex/config.toml`:

```toml
provider.openai.api_key = "opencode-go-switch"
provider.openai.base_url = "http://127.0.0.1:7878/v1"
model = "kimi-k2.6"
```

### Claude Code (VS Code)

`~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:7878",
    "ANTHROPIC_AUTH_TOKEN": "opencode-go-switch",
    "ANTHROPIC_MODEL": "minimax-m3"
  }
}
```

## 桌面 GUI

可选安装桌面版——原生窗口 + 系统托盘，双击即用：

```bash
pip install pywebview pystray Pillow
python desktop_app.py
```

关闭窗口自动最小化至系统托盘；托盘右键可恢复或退出（退出时自动停止服务）。

## 支持模型

### Codex (Chat Models)
kimi-k2.7/code, kimi-k2.6/2.5, deepseek-v4-pro/flash, glm-5.2/5.1/5, qwen3.7-max/plus, qwen3.6/3.5-plus, mimo-v2.5-pro, mimo-v2.5/v2-pro/omni, hy3-preview

### Claude Code (Anthropic Models)  
minimax-m3, minimax-m2.7/m2.5, glm-5.2/5.1/5, qwen3.7-max/plus, qwen3.6/3.5-plus

## 项目结构

```
opencode-go-switch/
├── server.py           # FastAPI 代理核心
├── desktop_app.py      # 桌面 GUI (pywebview)
├── start_gui.bat       # 桌面版启动脚本
├── generate_icon.py    # 图标生成
├── config.example.json # 配置模板
├── requirements.txt    # Python 依赖
├── static/             # Web 控制台静态文件
└── start.bat           # 命令行版启动脚本
```

## License

MIT
