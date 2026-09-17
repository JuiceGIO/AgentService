"""应用配置：统一从 .env / 环境变量读取。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/

# 优先读取仓库根目录 .env，其次 backend/.env
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "AgentService")
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs")))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/agentservice")

# Java 工单服务（起：转人工/投诉 → 自动建单闭环）
TICKET_SERVICE_URL = os.getenv("TICKET_SERVICE_URL", "http://127.0.0.1:8080")

# 演示用身份：会话未指定 user_id 时使用（对应 mock_data 里 ORD-20260828001/002 的归属人）
DEMO_USER_ID = os.getenv("DEMO_USER_ID", "u-1001")
