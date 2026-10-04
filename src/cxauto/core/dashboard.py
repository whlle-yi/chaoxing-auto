"""实时进度面板：显示工位状态、队列剩余、每个视频的播放进度。

使用 rich 在终端底部渲染固定区域；未安装 rich 时自动降级为纯日志模式。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from loguru import logger


def _fmt_seconds(seconds: int) -> str:
    """把秒数格式化为 mm:ss 或 h:mm:ss。"""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


@dataclass
class SlotState:
    """一个工位的实时状态。"""

    slot: int
    title: str = ""
    chapter_label: str = ""  # 章节「1.1 标题」形式，与学习通页面一致
    play_seconds: int = 0
    total_seconds: int = 0
    status: str = "空闲"  # 空闲 / 播放中


class Dashboard:
    """线程安全的进度状态汇总与渲染。

    工位线程只负责更新状态；渲染由 rich.Live 在主线程驱动，
    未安装 rich 时 ``render`` 返回 None，运行降级为纯日志。
    """

    def __init__(self, course_name: str, total_jobs: int, slot_count: int) -> None:
        self.course_name = course_name
        self.total_jobs = total_jobs
        self.queue_remaining = total_jobs
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self.started_at = time.monotonic()
        self.slots = [SlotState(slot=i + 1) for i in range(slot_count)]
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 状态更新（工位线程调用）

    def assign(self, slot: int, title: str, chapter_label: str) -> None:
        """工位领取了一个新视频。"""
        with self._lock:
            self.queue_remaining -= 1
            s = self.slots[slot]
            s.title = title
            s.chapter_label = chapter_label
            s.play_seconds = 0
            s.total_seconds = 0
            s.status = "播放中"

    def progress(self, slot: int, play_seconds: int, total_seconds: int) -> None:
        """视频心跳循环里每秒回报一次播放位置。"""
        with self._lock:
            s = self.slots[slot]
            s.play_seconds = play_seconds
            s.total_seconds = total_seconds

    def release(self, slot: int, result_value: str) -> None:
        """工位完成当前视频并释放。"""
        with self._lock:
            s = self.slots[slot]
            s.status = "空闲"
            s.title = ""
            s.chapter_label = ""
            s.play_seconds = 0
            s.total_seconds = 0
            if result_value == "completed":
                self.completed += 1
            elif result_value in ("skipped", "unsupported"):
                self.skipped += 1
            else:
                self.failed += 1

    # ------------------------------------------------------------------ 渲染（主线程调用）

    @property
    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def status_line(self) -> str:
        """单行文字进度（非动画环境下的降级输出）。"""
        with self._lock:
            parts = [
                f"工位{s.slot}: {s.title or '待补位'}"
                + (
                    f" {_fmt_seconds(s.play_seconds)}/{_fmt_seconds(s.total_seconds)}"
                    if s.total_seconds
                    else ""
                )
                for s in self.slots
            ]
            parts.append(
                f"已完成{self.completed} 失败{self.failed} 排队{self.queue_remaining}"
            )
        return " | ".join(parts)

    def render(self):
        """渲染为 rich 可渲染对象；rich 不可用时返回 None。"""
        try:
            from rich.console import Group
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text
        except ImportError:
            return None

        with self._lock:
            header = Text(
                f"已完成 {self.completed}   失败 {self.failed}   "
                f"排队中 {self.queue_remaining}/{self.total_jobs}   "
                f"已运行 {_fmt_seconds(self.elapsed_seconds)}",
            )
            table = Table.grid(padding=(0, 2))
            table.add_column(justify="right", style="bold")
            table.add_column()
            for s in self.slots:
                if s.status == "空闲":
                    table.add_row(f"工位{s.slot}", Text("等待补位…", style="dim"))
                    continue
                if s.total_seconds > 0:
                    ratio = min(1.0, s.play_seconds / s.total_seconds)
                    bar_len = 24
                    filled = int(ratio * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    pct = f"{ratio * 100:4.0f}%"
                    time_text = (
                        f"{_fmt_seconds(s.play_seconds)} / {_fmt_seconds(s.total_seconds)}"
                    )
                    detail = Text(f"{s.chapter_label}  {s.title}  ", overflow="crop")
                    detail.append(f"{bar} {pct}  ", style="cyan")
                    detail.append(time_text)
                else:
                    detail = Text(f"{s.chapter_label}  {s.title}  初始化…", overflow="crop")
                status_suffix = "" if s.status == "播放中" else f"  ⚠{s.status}"
                detail.append(status_suffix, style="yellow")
                table.add_row(f"工位{s.slot}", detail)

        return Panel(
            Group(header, table),
            title=f"cxauto · {self.course_name}",
            border_style="green",
        )


class DashboardLogger:
    """rich.Live 的包装。

    只有在真正的交互式终端里才启动原地动画（旧版控制台 / 重定向输出画不了，
    会堆出一帧帧残影），否则降级：由调用方定期输出单行文字进度。
    """

    def __init__(self) -> None:
        import sys

        self._live = None
        self._live_factory = None
        try:
            from rich.console import Console
            from rich.live import Live

            console = Console()
            if sys.stdout.isatty() and not console.legacy_windows:
                self._live_factory = lambda: Live(refresh_per_second=2, transient=False)
        except ImportError:
            pass

    @property
    def active(self) -> bool:
        """是否处于原地动画模式。"""
        return self._live is not None

    def __enter__(self):
        if self._live_factory is not None:
            self._live = self._live_factory()
            self._live.__enter__()
        return self

    def update(self, renderable) -> None:
        if self._live is not None and renderable is not None:
            self._live.update(renderable)

    def __exit__(self, *args) -> None:
        if self._live is not None:
            self._live.__exit__(*args)
            self._live = None
