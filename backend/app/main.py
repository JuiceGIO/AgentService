"""AgentService 入口：FastAPI + 健康检查 + 静态页托管 + HTTP/WS 对话接口。"""

import asyncio
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import APP_NAME
from .agent.react import run_agent_sync
from .delayed_queue import get_delayed_queue
from .jobs import DELAYED_TYPES, TASK_TYPES
from .logging_conf import setup_logging
from .session_store import get_session_store
from .task_queue import get_task_queue
from .ticket_client import TicketServiceError, list_tickets

setup_logging()

logger = logging.getLogger("app.main")

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title=APP_NAME, version="0.1.0")


class EchoRequest(BaseModel):
    message: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class TaskRequest(BaseModel):
    type: str
    args: dict = {}


class DelayedTaskRequest(BaseModel):
    type: str
    args: dict = {}
    delay_seconds: float = 0.0


class AccessLogMiddleware:
    """纯 ASGI 访问日志中间件（避免 BaseHTTPMiddleware 与 anyio 子进程管理的冲突）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "%s %s -> %s (%.1fms)",
                scope["method"],
                scope["path"],
                status["code"],
                (time.perf_counter() - start) * 1000,
            )


app.add_middleware(AccessLogMiddleware)


@app.get("/ping")
async def ping():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": "0.1.0",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "checks": {"api": "ok"}}


@app.post("/api/echo")
async def echo(payload: EchoRequest):
    """占位接口：网页 demo 先接 echo，后续替换为真 Agent。"""
    return {
        "reply": payload.message.strip(),
        "echo": True,
        "time": time.strftime("%H:%M:%S"),
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest):
    """单 Agent ReAct 循环，通过 MCP 调用业务工具后回复（在线程的独立事件循环中执行）。"""
    text = payload.message.strip()
    if not text:
        return {"reply": "请输入您的问题。", "steps": [], "mode": "rule", "escalated": False}
    return await asyncio.to_thread(run_agent_sync, text, None, payload.session_id)


@app.get("/api/sessions")
async def list_sessions():
    """会话侧栏：返回已保存的对话列表（按更新时间倒序）。"""
    store = get_session_store()
    sessions = await store.list_sessions()
    return {"sessions": sessions}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定对话。"""
    store = get_session_store()
    await store.clear(session_id)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/trace")
async def get_session_trace(session_id: str):
    """会话留痕（可回放）：用户问题、意图、工具步骤、回复。"""
    store = get_session_store()
    trace = await store.get_trace(session_id)
    return {"session_id": session_id, "trace": trace}


@app.get("/api/tickets")
async def tickets(session_id: str = ""):
    """工单状态查询（前端轮询：转人工后显示工单号/状态，含超时升级）。"""
    try:
        data = await asyncio.to_thread(list_tickets, session_id or None)
        return {"available": True, "session_id": session_id, "tickets": data}
    except TicketServiceError as exc:
        return {"available": False, "session_id": session_id, "tickets": [], "error": str(exc)}


@app.post("/api/tasks", status_code=202)
async def create_task(payload: TaskRequest):
    """提交异步任务（如批量建单），立即返回 task_id，进度走 GET 查询。"""
    fn = TASK_TYPES.get(payload.type)
    if not fn:
        raise HTTPException(status_code=404, detail=f"未知任务类型：{payload.type}")
    job = get_task_queue().submit(payload.type, fn, **(payload.args or {}))
    return job


@app.get("/api/tasks")
async def list_tasks(limit: int = 20):
    return {"tasks": get_task_queue().list(limit=limit)}


@app.get("/api/tasks/{task_id}")
async def task_status(task_id: str):
    job = get_task_queue().get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


delayed_queue = get_delayed_queue(DELAYED_TYPES)


@app.post("/api/delayed", status_code=202)
async def submit_delayed(payload: DelayedTaskRequest):
    """提交延迟任务（如 N 秒后自动建回访工单），调度线程到点投递 + 定时兜底。"""
    try:
        job = delayed_queue.submit(payload.type, payload.args or {}, payload.delay_seconds)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return job


@app.get("/api/delayed")
async def list_delayed(limit: int = 20):
    return {"tasks": delayed_queue.list(limit=limit)}


@app.get("/api/delayed/{job_id}")
async def delayed_status(job_id: str):
    job = delayed_queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="延迟任务不存在")
    return job


def _chunk_text(text: str, size: int = 3) -> list:
    return [text[i:i + size] for i in range(0, len(text), size)]


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket 客服对话：流式回复 + 会话记忆（Redis/内存），支持新会话重置。"""
    await websocket.accept()
    store = get_session_store()
    session_id = websocket.query_params.get("session_id") or ""
    if not session_id:
        session_id = uuid.uuid4().hex
        await websocket.send_json({"type": "session", "session_id": session_id})
    history = await store.get_history(session_id)
    # 重连时下发历史，让页面恢复上次对话气泡（刷新不丢）
    await websocket.send_json({"type": "history", "messages": history})
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if msg_type == "reset":
                await store.clear(session_id)
                history = []
                await websocket.send_json({"type": "reset_ok"})
                continue
            if msg_type != "user":
                continue
            text = (data.get("message") or "").strip()
            if not text:
                continue
            result = await asyncio.to_thread(run_agent_sync, text, list(history), session_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": result["reply"]})
            await store.append(session_id, "user", text)
            await store.append(session_id, "assistant", result["reply"])
            await store.append_trace(
                session_id,
                {
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "user": text,
                    "intent": result["intent"],
                    "confidence": result["confidence"],
                    "escalated": result["escalated"],
                    "steps": result["steps"],
                    "messages": result["messages"],
                    "reply": result["reply"],
                },
            )
            if result["steps"]:
                await websocket.send_json({"type": "steps", "steps": result["steps"]})
            for chunk in _chunk_text(result["reply"]):
                await websocket.send_json({"type": "token", "content": chunk})
                await asyncio.sleep(0.02)
            critic = next(
                (m for m in result["messages"] if m.get("role") == "critic"),
                None,
            )
            critic_verdict = critic.get("verdict", {}) if critic else {}
            await websocket.send_json(
                {
                    "type": "done",
                    "reply": result["reply"],
                    "mode": result["mode"],
                    "escalated": result["escalated"],
                    "intent": result["intent"],
                    "confidence": result["confidence"],
                    "critic_pass": critic_verdict.get("pass"),
                    "critic_escalate": critic_verdict.get("escalate"),
                    "messages": result["messages"],
                }
            )
    except WebSocketDisconnect:
        logger.info("WS 断开: %s", session_id)
    except Exception as exc:
        logger.exception("WS 错误: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
