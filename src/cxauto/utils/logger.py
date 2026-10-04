"""日志：loguru 配置（控制台 + 文件轮转）。"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_file: Path, level: str = "INFO") -> None:
    """初始化日志。控制台只输出指定级别，文件记录 DEBUG 级全量便于排查。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    )
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        encoding="utf-8",
    )


__all__ = ["logger", "setup_logger"]
