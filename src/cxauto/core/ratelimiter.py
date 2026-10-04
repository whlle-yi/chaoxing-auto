"""线程安全的通用限速器：保证相邻两次调用之间至少间隔 ``interval`` 秒（带随机抖动）。"""

from __future__ import annotations

import random
import threading
import time


class RateLimiter:
    """按最小间隔限速。视频日志上报这类接口对频率极敏感，必须限速 + 抖动。"""

    def __init__(self, interval: float, jitter: float = 0.0) -> None:
        """
        Args:
            interval: 相邻两次调用之间的最小间隔（秒）。
            jitter: 额外随机抖动的上限（秒），每次实际等待 [interval, interval + jitter]。
        """
        self.interval = interval
        self.jitter = jitter
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        """阻塞直到允许下一次调用。"""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            delay = self.interval + random.uniform(0.0, self.jitter) - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_call = time.monotonic()
