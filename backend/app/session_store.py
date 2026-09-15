"""会话存储：本地文件持久化（默认）+ Redis 镜像（可选，带 TTL），支持会话列表。"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import BASE_DIR, REDIS_URL

logger = logging.getLogger("app.session_store")

HISTORY_LIMIT = 20  # 保留最近 N 条消息，控制上下文长度
TRACE_LIMIT = 50  # 每个会话保留最近 N 轮留痕（可回放）
TTL_SECONDS = 86400  # 会话 24 小时过期
DATA_FILE = BASE_DIR / "data" / "sessions.json"


class SessionStore:
    def __init__(self, redis_url: str = REDIS_URL, data_file: Path = DATA_FILE):
        self._redis_url = redis_url
        self._data_file = data_file
        self._redis = None
        self._sessions = {}  # session_id -> {"history": [...], "meta": {...}}
        self._lock = asyncio.Lock()
        self._checked = False
        self._load()

    def _load(self):
        """启动时从本地文件加载会话（保证重启不丢）。"""
        try:
            if self._data_file.exists():
                raw = self._data_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                for sid, item in data.items():
                    item.setdefault("history", [])
                    item.setdefault("meta", {})
                    item.setdefault("trace", [])
                    self._sessions[sid] = item
                if self._sessions:
                    logger.info("会话存储：已从文件加载 %d 个会话", len(self._sessions))
        except Exception as exc:
            logger.warning("会话文件读取失败：%s", exc)

    async def _persist(self):
        """把全部会话写回本地文件（先写临时文件再替换，避免写坏）。"""
        async with self._lock:
            data = json.dumps(self._sessions, ensure_ascii=False)
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._data_file.with_suffix(".json.tmp")
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(self._data_file)
        except Exception as exc:
            logger.warning("会话文件写入失败：%s", exc)

    async def _ensure_redis(self):
        """首次使用时探测 Redis；失败则回退内存。"""
        if self._checked:
            return
        self._checked = True
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self._redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
            logger.info("会话存储：Redis 已连接")
        except Exception as exc:
            self._redis = None
            logger.warning("会话存储：Redis 不可用，使用本地文件持久化：%s", exc)

    def _key(self, session_id: str) -> str:
        return f"agent:session:{session_id}"

    async def get_history(self, session_id: str) -> list:
        if not session_id:
            return []
        async with self._lock:
            item = self._sessions.get(session_id)
            return list(item["history"]) if item else []

    async def append(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        async with self._lock:
            item = self._sessions.setdefault(session_id, {"history": [], "meta": {}})
            item["history"].append({"role": role, "content": content})
            item["history"] = item["history"][-HISTORY_LIMIT:]
            meta = item["meta"]
            if role == "user" and "title" not in meta:
                meta["title"] = content[:20]
            meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
            meta["count"] = len(item["history"])
        await self._mirror(session_id)
        await self._persist()

    async def _mirror(self, session_id: str) -> None:
        """把会话镜像到 Redis（带 TTL），Redis 可用时启用。"""
        await self._ensure_redis()
        if self._redis is None:
            return
        try:
            async with self._lock:
                history = self._sessions[session_id]["history"]
            await self._redis.setex(
                self._key(session_id),
                TTL_SECONDS,
                json.dumps(history, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning("Redis 镜像写入失败：%s", exc)

    async def list_sessions(self) -> list:
        """按更新时间倒序返回会话列表（含标题/条数/时间），自动剔除过期会话。"""
        now = datetime.now()
        out = []
        async with self._lock:
            for sid, item in self._sessions.items():
                meta = item.get("meta", {})
                updated = meta.get("updated_at")
                if not updated:
                    continue
                try:
                    ts = datetime.fromisoformat(updated)
                except Exception:
                    continue
                if now - ts > timedelta(seconds=TTL_SECONDS):
                    continue
                out.append(
                    {
                        "session_id": sid,
                        "title": meta.get("title", "新对话"),
                        "updated_at": updated,
                        "count": meta.get("count", 0),
                    }
                )
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    async def append_trace(self, session_id: str, entry: dict) -> None:
        """记录一轮对话的留痕（用户问题/意图/工具步骤/回复），用于回放与审计。"""
        if not session_id:
            return
        async with self._lock:
            item = self._sessions.setdefault(session_id, {"history": [], "meta": {}})
            item.setdefault("trace", []).append(entry)
            item["trace"] = item["trace"][-TRACE_LIMIT:]
        await self._persist()

    async def get_trace(self, session_id: str) -> list:
        if not session_id:
            return []
        async with self._lock:
            item = self._sessions.get(session_id)
            return list(item.get("trace", [])) if item else []

    async def clear(self, session_id: str) -> None:
        if not session_id:
            return
        async with self._lock:
            self._sessions.pop(session_id, None)
        await self._persist()
        await self._ensure_redis()
        if self._redis is not None:
            try:
                await self._redis.delete(self._key(session_id))
            except Exception:
                pass


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
