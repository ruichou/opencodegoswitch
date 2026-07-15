#!/usr/bin/env python3
"""
OpenCode Go Switch — 本地代理
==============================
OpenCode Go Chat Completions API → Codex Responses API 转换
同时支持 Claude Code (Anthropic Messages) 和直通 Chat Completions
"""

import json, os, sys, re, time, uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

# ── Config ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"

_CFG = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
API_KEY = _CFG.get("api_key", "")
CURRENT_MODEL = _CFG.get("current_model", "kimi-k2.6")
CURRENT_ANTHROPIC_MODEL = _CFG.get("current_anthropic_model", "minimax-m3")
PORT = _CFG.get("port", 7878)
UPSTREAM_BASE = "https://opencode.ai/zen/go/v1"

def save_config():
    CONFIG_FILE.write_text(json.dumps({
        "api_key": API_KEY, "current_model": CURRENT_MODEL,
        "current_anthropic_model": CURRENT_ANTHROPIC_MODEL,
        "port": PORT, "host": "127.0.0.1"
    }, indent=2))

# ── Model List ──────────────────────────────────────────
CHAT_MODELS = {
    "kimi-k2.7-code":    "Kimi K2.7 Code",
    "kimi-k2.6":         "Kimi K2.6",
    "kimi-k2.5":         "Kimi K2.5",
    "deepseek-v4-pro":   "DeepSeek V4 Pro",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "glm-5.2":           "GLM-5.2",
    "glm-5.1":           "GLM-5.1",
    "glm-5":             "GLM-5",
    "qwen3.7-max":       "Qwen3.7 Max",
    "qwen3.7-plus":      "Qwen3.7 Plus",
    "qwen3.6-plus":      "Qwen3.6 Plus",
    "qwen3.5-plus":      "Qwen3.5 Plus",
    "mimo-v2.5-pro":     "MiMo V2.5 Pro",
    "mimo-v2.5":         "MiMo V2.5",
    "mimo-v2-pro":       "MiMo V2 Pro",
    "mimo-v2-omni":      "MiMo V2 Omni",
    "hy3-preview":       "HY3 Preview",
}
ANTHROPIC_MODELS = {
    "minimax-m3":        "MiniMax M3",
    "minimax-m2.7":      "MiniMax M2.7",
    "minimax-m2.5":      "MiniMax M2.5",
    "glm-5.2":           "GLM-5.2",
    "glm-5.1":           "GLM-5.1",
    "glm-5":             "GLM-5",
    "qwen3.7-max":       "Qwen3.7 Max",
    "qwen3.7-plus":      "Qwen3.7 Plus",
    "qwen3.6-plus":      "Qwen3.6 Plus",
    "qwen3.5-plus":      "Qwen3.5 Plus",
}

app = FastAPI(title="OpenCode Go Switch")

# ── /v1 base route (Codex doctor probes this) ──────────
@app.get("/v1")
@app.get("/v1/")
async def v1_root():
    return {"object": "list", "message": "OpenCode Go Switch v1"}

# ── Helpers ─────────────────────────────────────────────

def talk_to_openai(body: dict) -> dict:
    """Send request to upstream Chat Completions API (non-streaming)."""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    body = dict(body)
    body["stream"] = False
    r = httpx.post(f"{UPSTREAM_BASE}/chat/completions", json=body, headers=headers, timeout=300)
    if r.status_code != 200:
        raise HTTPException(r.status_code, detail=r.text)
    return r.json()

async def stream_from_openai(client: httpx.AsyncClient, body: dict, headers: dict):
    """Stream from upstream Chat Completions API. Yields raw SSE lines."""
    body = dict(body)
    body["stream"] = True
    async with client.stream("POST", f"{UPSTREAM_BASE}/chat/completions",
                              json=body, headers=headers, timeout=300) as r:
        if r.status_code != 200:
            body_text = await r.aread()
            print(f"[UPSTREAM ERROR] {r.status_code}: {body_text[:500]}", file=sys.stderr)
            raise HTTPException(r.status_code, detail=body_text.decode(errors="replace"))
        async for line in r.aiter_lines():
            yield line

def chat_to_responses_sse_stream(chat_body: dict, model: str):
    """Convert upstream Chat Completions SSE stream → Codex Responses API SSE stream.
    
    This is the core conversion. Based on CC Switch's streaming_codex_chat.rs pattern:
    - Real streaming: process each chunk as it arrives
    - No [DONE] marker — stream ends naturally
    - Complete SSE lifecycle events
    """

    async def generate():
        t0 = int(time.time())
        resp_id = f"resp_{uuid.uuid4().hex[:12]}"
        msg_id = f"{resp_id}_msg"
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        accumulated_text = ""
        state = "init"  # init → streaming → done

        async with httpx.AsyncClient(timeout=300) as client:
            chat_body_copy = dict(chat_body)
            chat_body_copy["stream"] = True
            chat_body_copy["model"] = model

            try:
                async with client.stream("POST", f"{UPSTREAM_BASE}/chat/completions",
                                         json=chat_body_copy, headers=headers, timeout=300) as r:
                    if r.status_code != 200:
                        body_text = await r.aread()
                        print(f"[UPSTREAM ERROR] {r.status_code}", file=sys.stderr)
                        err = json.dumps({"error": f"Upstream {r.status_code}"})
                        yield f"data: {err}\n\n"
                        return

                    print(f"[STREAM] Connected to upstream, status={r.status_code}", file=sys.stderr)

                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]  # strip "data: "
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")

                        if state == "init":
                            # First chunk: emit created + in_progress
                            base = {"id": resp_id, "object": "response", "created_at": t0,
                                    "status": "in_progress", "model": model, "output": [], "usage": None}
                            yield f"event: response.created\ndata: {json.dumps({'type': 'response.created', 'response': base})}\n\n"
                            yield f"event: response.in_progress\ndata: {json.dumps({'type': 'response.in_progress', 'response': base})}\n\n"
                            state = "streaming"

                        if content:
                            if accumulated_text == "" and state == "streaming":
                                # First content: emit output_item + content_part
                                msg_item = {"id": msg_id, "type": "message", "status": "in_progress",
                                            "role": "assistant", "content": []}
                                yield f"event: response.output_item.added\ndata: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': msg_item})}\n\n"
                                part = {"type": "output_text", "text": "", "annotations": []}
                                yield f"event: response.content_part.added\ndata: {json.dumps({'type': 'response.content_part.added', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': part})}\n\n"

                            accumulated_text += content
                            # Emit delta
                            yield f"event: response.output_text.delta\ndata: {json.dumps({'type': 'response.output_text.delta', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'delta': content})}\n\n"

                    # Stream ended — emit completion events
                    print(f"[STREAM] Done, total text len={len(accumulated_text)}", file=sys.stderr)

                    if accumulated_text:
                        # output_text.done
                        yield f"event: response.output_text.done\ndata: {json.dumps({'type': 'response.output_text.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'text': accumulated_text})}\n\n"
                        # content_part.done
                        part_done = {"type": "output_text", "text": accumulated_text, "annotations": []}
                        yield f"event: response.content_part.done\ndata: {json.dumps({'type': 'response.content_part.done', 'item_id': msg_id, 'output_index': 0, 'content_index': 0, 'part': part_done})}\n\n"
                        # output_item.done
                        msg_completed = {"id": msg_id, "type": "message", "status": "completed", "role": "assistant",
                                        "content": [{"type": "output_text", "text": accumulated_text, "annotations": []}]}
                        yield f"event: response.output_item.done\ndata: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': msg_completed})}\n\n"

                    # response.completed
                    t1 = int(time.time())
                    completed = {"id": resp_id, "object": "response", "created_at": t0,
                                "status": "completed", "model": model,
                                "output": [msg_completed] if accumulated_text else [],
                                "usage": {"input_tokens": 0, "output_tokens": len(accumulated_text)//4, "total_tokens": len(accumulated_text)//4}}
                    yield f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': completed})}\n\n"

                    # NOTE: No [DONE] marker! CC Switch ends stream naturally.

            except Exception as e:
                print(f"[STREAM ERROR] {e}", file=sys.stderr)
                err_resp = {"error": {"message": str(e), "type": "proxy_error"}}
                yield f"data: {json.dumps(err_resp)}\n\n"

    return generate


# ── /v1/responses — Codex (Responses API → Chat Completions) ──
@app.post("/v1/responses")
async def handle_responses(request: Request):
    body = await request.json()
    # IGNORE Codex's model — always use our configured model
    codex_model = body.get("model", "")
    model = CURRENT_MODEL
    if codex_model and codex_model != model:
        print(f"[RESPONSES] Overriding model: {codex_model} → {model}", file=sys.stderr)
    stream = body.get("stream", True)
    raw_input = body.get("input", "")

    # Normalize input: Codex sends input as string or array of messages
    messages = []
    if isinstance(raw_input, str):
        messages = [{"role": "user", "content": raw_input}]
    elif isinstance(raw_input, list):
        for item in raw_input:
            role = item.get("role", "user")
            if role == "system":
                messages.append({"role": "system", "content": item.get("content", "")})
            elif role in ("user", "assistant"):
                parts = item.get("content", [])
                if isinstance(parts, str):
                    messages.append({"role": role, "content": parts})
                elif isinstance(parts, list):
                    texts = []
                    for p in parts:
                        if isinstance(p, dict) and p.get("type") == "input_text":
                            texts.append(p.get("text", ""))
                        elif isinstance(p, str):
                            texts.append(p)
                    messages.append({"role": role, "content": "\n".join(texts)})

    # Deduplicate repeated system messages (Codex reinjects full system prompt each turn)
    seen_system = set()
    clean = []
    for m in messages:
        if m["role"] == "system":
            key = m["content"][:100]
            if key in seen_system:
                continue
            seen_system.add(key)
        clean.append(m)

    # Limit conversation history to avoid huge requests
    if len(clean) > 10:
        # Keep first system message + last N messages
        system_msgs = [m for m in clean if m["role"] == "system"]
        non_system = [m for m in clean if m["role"] != "system"]
        clean = system_msgs[:1] + non_system[-8:]

    chat_body = {"model": model, "messages": clean}

    print(f"[RESPONSES] model={model} stream={stream} msgs={len(clean)}", file=sys.stderr)

    if not stream:
        resp = talk_to_openai(chat_body)
        msg = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {})
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        return {
            "id": response_id, "object": "response", "created_at": int(time.time()),
            "status": "completed", "model": model,
            "output": [{"id": f"{response_id}_msg", "type": "message", "status": "completed",
                       "role": "assistant", "content": [{"type": "output_text", "text": msg}]}],
            "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                     "output_tokens": usage.get("completion_tokens", 0),
                     "total_tokens": usage.get("total_tokens", 0)}
        }

    return StreamingResponse(chat_to_responses_sse_stream(chat_body, model)(), media_type="text/event-stream")


# ── /v1/chat/completions — 直通 ──
@app.post("/v1/chat/completions")
async def handle_chat(request: Request):
    body = await request.json()
    stream = body.get("stream", False)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    if not stream:
        return talk_to_openai(body)

    async def passthrough():
        async with httpx.AsyncClient(timeout=300) as c:
            async for line in stream_from_openai(c, body, headers):
                yield line + "\n"
    return StreamingResponse(passthrough(), media_type="text/event-stream")


# ── /v1/messages — Claude Code (Anthropic Messages) ──
@app.post("/v1/messages")
async def handle_messages(request: Request):
    body = await request.json()
    body["model"] = CURRENT_ANTHROPIC_MODEL  # Force configured model
    stream = body.get("stream", False)

    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json",
    }
    client_av = request.headers.get("anthropic-version")
    if client_av:
        headers["anthropic-version"] = client_av

    print(f"[MESSAGES] stream={stream} model={body.get('model')}", file=sys.stderr)

    if stream:
        # Stream mode: unbuffered byte-level passthrough for minimal latency
        async def sse_passthrough():
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{UPSTREAM_BASE}/messages", json=body, headers=headers) as r:
                    if r.status_code != 200:
                        err = await r.aread()
                        print(f"[MESSAGES] SSE ERROR: {r.status_code} {err[:300]}", file=sys.stderr)
                        raise HTTPException(r.status_code, detail=err.decode())
                    buf = ""
                    async for chunk in r.aiter_bytes(chunk_size=64):
                        buf += chunk.decode(errors="replace")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            yield line + "\n"
                    if buf:
                        yield buf
        return StreamingResponse(
            sse_passthrough(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
        )
    else:
        r = httpx.post(f"{UPSTREAM_BASE}/messages", json=body, headers=headers, timeout=300)
        if r.status_code != 200:
            print(f"[MESSAGES] ERROR: {r.status_code} {r.text[:300]}", file=sys.stderr)
            raise HTTPException(r.status_code, detail=r.text)
        return r.json()


# ── /v1/models ──────────────────────────────────────────
@app.get("/v1/models")
async def list_models():
    models = []
    for mid, name in CHAT_MODELS.items():
        models.append({"id": mid, "object": "model", "owned_by": "opencode"})
    for mid, name in ANTHROPIC_MODELS.items():
        models.append({"id": mid, "object": "model", "owned_by": "opencode"})
    return {"object": "list", "data": models}


# ── Web Console ─────────────────────────────────────────
WEB_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenCode Go Switch</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#333;min-height:100vh}
.container{max-width:680px;margin:0 auto;padding:24px}
h1{font-size:26px;margin-bottom:6px;color:#1a1a2e}
.subtitle{color:#888;font-size:14px;margin-bottom:28px}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600}
.badge-codex{background:#eef2ff;color:#4f46e5}
.badge-claude{background:#fef3c7;color:#d97706}
.card{background:#fff;border-radius:10px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.card h2{font-size:15px;margin-bottom:14px;color:#444;display:flex;align-items:center;gap:8px}
.model-list{display:flex;flex-wrap:wrap;gap:10px}
.model-btn{padding:10px 18px;border:2px solid #e5e7eb;border-radius:8px;background:#fafafa;cursor:pointer;font-size:13px;transition:all .2s;position:relative;font-weight:500}
.model-btn:hover{border-color:#818cf8;background:#eef2ff;transform:translateY(-1px);box-shadow:0 2px 6px rgba(99,102,241,0.15)}
.model-btn.active{background:#4f46e5;color:#fff;border-color:#4f46e5;font-weight:600;box-shadow:0 2px 8px rgba(79,70,229,0.3)}
.model-btn.active::before{content:"✓ ";font-size:11px}
.model-btn.anthropic.active{background:#d97706;border-color:#d97706;box-shadow:0 2px 8px rgba(217,119,6,0.3)}
.model-btn.anthropic:hover{border-color:#f59e0b;background:#fffbeb}
.hint{font-size:11px;color:#aaa;margin-top:8px}
.endpoints{font-size:13px;color:#666;line-height:1.8}
.endpoints code{background:#f0f0f0;padding:2px 6px;border-radius:3px;font-size:12px}
.status{display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;margin-right:6px}
.footer{margin-top:24px;text-align:center;color:#aaa;font-size:12px}
</style>
</head>
<body>
<div class="container">
  <h1>🔧 OpenCode Go Switch</h1>
  <p class="subtitle">本地代理运行中 · 端口 {port}</p>
  
  <div class="card">
    <h2><span class="badge badge-codex">Codex</span> 当前模型：<b style="color:#4f46e5">{current_model}</b></h2>
    <p class="hint">👇 点击下方按钮切换 Codex 使用的模型</p>
    <div class="model-list" id="chatModels"></div>
  </div>
  
  <div class="card">
    <h2><span class="badge badge-claude">Claude Code</span> 当前模型：<b style="color:#d97706">{current_anthropic_model}</b></h2>
    <p class="hint">👇 点击下方按钮切换 Claude Code 使用的模型</p>
    <div class="model-list" id="anthropicModels"></div>
  </div>
  
  <div class="card">
    <h2>代理端点</h2>
    <div class="endpoints">
      <p><code>POST /v1/responses</code> → Codex</p>
      <p><code>POST /v1/messages</code> → Claude Code</p>
      <p><code>POST /v1/chat/completions</code> → 直通</p>
    </div>
  </div>
  
  <p class="footer"><span class="status"></span> 服务运行中</p>
</div>

<script>
const CURRENT_CHAT = "{current_model}";
const CURRENT_ANTHROPIC = "{current_anthropic_model}";
const chat = {chat_model_list};
const anthropic = {anthropic_model_list};
async function setModel(key, id) {
  await fetch("/api/config", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:key,value:id})});
  location.reload();
}
function renderList(list, containerId, active, isAnthropic) {
  const c = document.getElementById(containerId);
  list.forEach(m => {
    const btn = document.createElement("button");
    const cls = "model-btn" + (isAnthropic?" anthropic":"") + (m===active?" active":"");
    btn.className = cls;
    btn.textContent = m;
    btn.onclick = () => setModel(containerId==="chatModels"?"current_model":"current_anthropic_model", m);
    c.appendChild(btn);
  });
}
renderList(chat, "chatModels", CURRENT_CHAT, false);
renderList(anthropic, "anthropicModels", CURRENT_ANTHROPIC, true);
</script>
</body>
</html>
"""

@app.get("/")
async def web_console():
    html = (WEB_HTML
        .replace("{port}", str(PORT))
        .replace("{current_model}", CURRENT_MODEL)
        .replace("{current_anthropic_model}", CURRENT_ANTHROPIC_MODEL)
        .replace("{chat_model_list}", json.dumps(list(CHAT_MODELS.keys())))
        .replace("{anthropic_model_list}", json.dumps(list(ANTHROPIC_MODELS.keys())))
    )
    return HTMLResponse(html)


# ── /api/config ─────────────────────────────────────────
class ConfigUpdate(BaseModel):
    key: str
    value: str

@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    global CURRENT_MODEL, CURRENT_ANTHROPIC_MODEL, API_KEY, PORT
    if update.key == "current_model":
        CURRENT_MODEL = update.value
    elif update.key == "current_anthropic_model":
        CURRENT_ANTHROPIC_MODEL = update.value
    elif update.key == "api_key":
        API_KEY = update.value
    elif update.key == "port":
        PORT = int(update.value)
    save_config()
    return {"ok": True}


# ── Entry ───────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n  OpenCode Go Switch → http://127.0.0.1:{PORT}")
    print(f"  Model: {CURRENT_MODEL}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
