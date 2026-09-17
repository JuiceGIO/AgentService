"""会话存储（三层记忆）。

工作记忆：最近 HISTORY_LIMIT 条消息（内存 + 本地文件持久化 + Redis 镜像，带 TTL）
摘要记忆：超过 SUMMARY_TRIGGER 条时，把较老的消息压缩成一段摘要（规则版，无需 LLM）
长期偏好：用户级键值（profiles.json），跨会话保留，用于个性化回答
"""

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
SUMMARY_TRIGGER = 12  # 工作记忆超过 N 条时把较老的消息压成摘要（必须小于 HISTORY_LIMIT）
RECENT_KEEP = 10  # 摘要后仍保留在上下文里的最近消息数
DATA_FILE = BASE_DIR / "data" / "sessions.json"
PROFILE_FILE = BASE_DIR / "data" / "profiles.json"


class SessionStore:
    def __init__(self, redis_url: str = REDIS_URL, data_file: Path = DATA_FILE):
        self._redis_url = redis_url
        self._data_file = data_file
        self._profile_file = data_file.parent / PROFILE_FILE.name
        self._profiles = {}  # user_id -> {key: value}
        self._redis = None
        self._sessions = {}  # session_id -> {"history": [...], "meta": {...}}
        self._lock = asyncio.Lock()
        self._checked = False
        self._load()
        self._load_profiles()

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

    def _load_profiles(self):
        """长期偏好：用户级键值，跨会话保留。"""
        try:
            if self._profile_file.exists():
                self._profiles = json.loads(self._profile_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("用户偏好文件读取失败：%s", exc)

    def _persist_profiles(self):
        try:
            self._profile_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._profile_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._profiles, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._profile_file)
        except Exception as exc:
            logger.warning("用户偏好写入失败：%s", exc)

    async def set_user(self, session_id: str, user_id: str) -> None:
        """把会话绑定到身份（user_id）：后续工具调用用它做行级权限校验。"""
        if not session_id or not user_id:
            return
        async with self._lock:
            item = self._sessions.setdefault(session_id, {"history": [], "meta": {}})
            item["meta"]["user_id"] = user_id
        await self._persist()

    def get_user(self, session_id: str) -> str:
        item = self._sessions.get(session_id) or {}
        return (item.get("meta") or {}).get("user_id", "")

    def get_profile(self, user_id: str) -> dict:
        return dict(self._profiles.get(user_id, {}))

    async def set_profile(self, user_id: str, key: str, value) -> dict:
        """写长期偏好（用户级）。"""
        if not user_id or not key:
            return {}
        profile = self._profiles.setdefault(user_id, {})
        profile[key] = value
        self._persist_profiles()
        return dict(profile)

    @staticmethod
    def _summarize(history: list) -> str:
        """摘要记忆：把较老的消息压成一段话（规则版，可替换为 LLM 摘要）。

        规则版只保留结构性信息（轮数 + 早期诉求 + 出现过的意图关键词），
        好处是无外部依赖、可复现；接 LLM 后只需替换这个函数。
        """
        user_msgs = [m.get("content", "") for m in history if m.get("role") == "user"]
        if not user_msgs:
            return ""
        head = "；".join(x[:20] for x in user_msgs[:3])
        return f"早期共 {len(user_msgs)} 轮用户消息，诉求摘要：{head}"

    async def build_context(self, session_id: str) -> dict:
        """组装三层记忆：工作记忆（最近消息）+ 摘要记忆 + 用户长期偏好。"""
        if not session_id:
            return {"summary": "", "recent": [], "profile": {}, "user_id": ""}
        async with self._lock:
            item = self._sessions.get(session_id) or {}
            history = list(item.get("history", []))
            meta = dict(item.get("meta", {}))
        summary = meta.get("summary", "")
        if len(history) > SUMMARY_TRIGGER:
            summary = self._summarize(history[:-RECENT_KEEP])
            async with self._lock:
                self._sessions.setdefault(session_id, {"history": [], "meta": {}})["meta"]["summary"] = summary
            await self._persist()
        user_id = meta.get("user_id", "")
        return {
            "summary": summary,
            "recent": history[-RECENT_KEEP:],
            "profile": self.get_profile(user_id) if user_id else {},
            "user_id": user_id,
        }

    @staticmethod
    def build_context_note(context: dict) -> str:
        """把三层记忆拼成给 Agent 的一段上下文说明（无内容时返回空串）。"""
        parts = []
        if context.get("user_id"):
            parts.append(f"当前用户身份：{context['user_id']}（工具调用只能访问该身份名下的订单/工单）")
        if context.get("summary"):
            parts.append(f"会话摘要：{context['summary']}")
        profile = context.get("profile") or {}
        if profile:
            parts.append("用户长期偏好：" + "；".join(f"{k}={v}" for k, v in profile.items()))
        if not parts:
            return ""
        return "【记忆上下文】\n" + "\n".join(parts)

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
            meta = item["meta"]
            # 摘要记忆：在截断工作记忆之前，把较老的部分压成摘要（否则被截断的消息永久丢失）
            if len(item["history"]) > SUMMARY_TRIGGER:
                meta["summary"] = self._summarize(item["history"][:-RECENT_KEEP])
            item["history"] = item["history"][-HISTORY_LIMIT:]
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
