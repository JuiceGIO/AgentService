"""日志配置：控制台 + 文件（logs/app.log），文件按大小轮转。"""

import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR


def setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # 避免 --reload 时重复添加 handler
    if root.handlers:
        return

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root.addHandler(console)
    root.addHandler(file_handler)
