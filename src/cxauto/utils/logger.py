"""日志：loguru 配置（控制台 + 文件轮转）。"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


class DynamicStream:
    """写入时才解析 ``sys.stdout`` 的代理流。

    loguru 在 add() 时捕获传入的流对象；rich Live 的重定向是替换
    ``sys.stdout`` 名字。直接传原始对象会让 loguru 绕过重定向、
    打乱 Live 的重画坐标（面板残影的根源）。此代理保证日志永远
    走"当前"的 stdout，被 Live 正确接管。
    """

    def __init__(self, name: str = "stdout") -> None:
        self._name = name

    def write(self, s: str) -> int:
        return getattr(sys, self._name).write(s)

    def flush(self) -> None:
        getattr(sys, self._name).flush()

    def isatty(self) -> bool:
        try:
            return getattr(sys, self._name).isatty()
        except Exception:  # noqa: BLE001
            return False


def setup_logger(log_file: Path, level: str = "INFO") -> None:
    """初始化日志。

    控制台走 stdout（与 rich Live 同通道，且通过动态代理让 Live 的
    重定向能接管日志输出，日志行出现在面板上方）。文件记录 DEBUG 全量。
    """
    logger.remove()
    logger.add(
        DynamicStream("stdout"),
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
