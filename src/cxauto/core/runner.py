"""任务调度：登录 -> 课程 -> 任务队列 -> 多工位滚动刷视频。

调度模型（用户指定的「工位制」）：
- 全课程的视频任务点排成一个队列（保持章节顺序）；
- ``concurrency`` 个工位各领一个视频同时刷；
- 某个视频刷完后，该工位先歇 ``slot_gap`` 秒再从队列取下一个，
  因此各视频启动/结束时间天然错开，且同时在线数恒不超过工位数。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from loguru import logger

from ..api.client import ChaoxingClient
from ..api.course import CourseAPI
from ..api.study import StudyAPI, StudyResult
from ..core.config import MAX_CONCURRENCY, Config
from ..core.models import Chapter, Course, Job
from .dashboard import Dashboard, DashboardLogger

RETRYABLE_RESULTS = (StudyResult.FAILED, StudyResult.FORBIDDEN)


@dataclass
class Stats:
    """运行统计。"""

    completed: int = 0
    skipped: int = 0
    failed: int = 0
    unsupported: int = 0

    def add(self, result: StudyResult) -> None:
        if result == StudyResult.COMPLETED:
            self.completed += 1
        elif result == StudyResult.SKIPPED:
            self.skipped += 1
        elif result == StudyResult.UNSUPPORTED:
            self.unsupported += 1
        else:
            self.failed += 1


class Runner:
    """刷课主流程：串行收集任务、多工位并行消化。"""

    def __init__(self, config: Config, show_panel: bool = True) -> None:
        self.config = config
        self.client = ChaoxingClient(config)
        self.course_api = CourseAPI(self.client)
        # 停止信号：GUI 的停止按钮置位后，工位在安全点（心跳间隙）退出
        self.stop_event = threading.Event()
        self.study_api = StudyAPI(self.client, speed=config.speed, stop_event=self.stop_event)
        self.stats = Stats()
        self._stats_lock = threading.Lock()
        # 当前进度面板引用（GUI 轮询显示用）
        self.dashboard: Dashboard | None = None
        # show_panel=False：终端侧不打印面板快照（GUI 模式由界面承担进度展示）
        self.show_panel = show_panel
        # 动态并行：工位数可在运行中通过 set_concurrency 调整（上限 3）
        self.target_workers = max(1, min(MAX_CONCURRENCY, config.concurrency))
        self._worker_threads: list[threading.Thread] = []
        self._wlock = threading.Lock()
        self._next_slot = 0
        self._run_ctx: tuple | None = None  # (course, job_queue, dashboard, panel)

    def apply_live_settings(self, concurrency: int | None = None,
                            speed: float | None = None) -> None:
        """刷课运行中热更新设置（GUI 的「保存配置」按钮调用）。"""
        if concurrency is not None:
            self.set_concurrency(concurrency)
        if speed is not None:
            self.study_api.speed = min(2.0, max(1.0, speed))
            logger.info("倍速调整为 {}x", self.study_api.speed)

    def set_concurrency(self, count: int) -> None:
        """运行中调整并行工位数（GUI 的并行数设置实时生效）。

        调大：立即补开新工位；调小：多出的工位在刷完当前视频后自行退出。
        """
        count = max(1, min(MAX_CONCURRENCY, count))
        self.target_workers = count
        ctx = self._run_ctx
        if ctx is None:
            return
        with self._wlock:
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            alive = len(self._worker_threads)
        for _ in range(count - alive):
            self._spawn_worker()
        logger.info("并行数调整为 {} 个工位", count)

    def run(self) -> Stats:
        """入口：登录并依次处理所有目标课程。"""
        self.client.login()
        courses = self.course_api.get_course_list(
            name_filter=self.config.course_list or None
        )
        if not courses:
            logger.warning("没有匹配到任何课程，请检查 course_list 配置")
            return self.stats

        for i, course in enumerate(courses, 1):
            logger.info("=" * 60)
            logger.info("[{}/{}] 开始处理课程: {}", i, len(courses), course.name)
            try:
                self._run_course(course)
            except Exception as e:  # noqa: BLE001 —— 单课程失败不影响后续课程
                logger.exception("课程处理异常，跳过: {}", e)

        logger.info("=" * 60)
        logger.info(
            "全部完成：成功 {}，跳过 {}，失败 {}，不支持 {}",
            self.stats.completed, self.stats.skipped, self.stats.failed, self.stats.unsupported,
        )
        return self.stats

    # ------------------------------------------------------------------ 课程

    def _run_course(self, course: Course) -> None:
        """收集一门课的全部视频任务点，然后用工位制并行消化。"""
        chapters = self.course_api.get_chapter_list(course)
        pending = [
            ch for ch in chapters
            if not ch.has_finished and not (ch.need_unlock and self.config.notopen_action == "skip")
        ]
        logger.info("待处理章节 {}/{}", len(pending), len(chapters))

        # 阶段一：串行抓取任务卡片，按章节顺序收集视频任务点
        all_jobs: list[tuple[Chapter, Job]] = []
        for ch in pending:
            if ch.need_unlock:
                if self.config.notopen_action == "stop":
                    logger.info("章节 {} 未开放，按配置停止收集", ch.index)
                    break
                logger.debug("章节 {} 未开放，跳过", ch.index)
                continue
            cards = self.course_api.get_cards(course, ch)
            for card in cards:
                for job in card.attachments:
                    if job.is_passed:
                        continue
                    # 只处理配置允许的任务类型（默认仅 video），其余一律不动
                    if job.type.value not in self.config.job_types:
                        logger.debug("跳过非视频任务点 [{}]: {}", job.type.value, job.title)
                        continue
                    all_jobs.append((ch, job))
        if not all_jobs:
            logger.info("课程《{}》没有待刷的视频任务点", course.name)
            return

        self.target_workers = min(self.target_workers, len(all_jobs))
        logger.info(
            "任务队列：{} 个视频，{} 个工位同时刷（补位间隔 {}s，运行中可调整）",
            len(all_jobs), self.target_workers, self.config.slot_gap,
        )

        # 阶段二：工位滚动消费任务队列（工位数可运行中调整）
        job_queue: queue.Queue = queue.Queue()
        for item in all_jobs:
            job_queue.put(item)

        dashboard = Dashboard(course.name, total_jobs=len(all_jobs), slot_count=1)
        self.dashboard = dashboard
        panel = DashboardLogger() if (self.show_panel and not self.config.live_dashboard) else None
        self._run_ctx = (course, job_queue, dashboard, panel)
        if panel:
            panel.snapshot(dashboard.render())

        for _ in range(self.target_workers):
            self._spawn_worker()

        if self.config.live_dashboard:
            # 真终端里的原地动画模式（--live 开启）。
            # redirect_stdout 让日志行出现在面板上方而不是打乱重画坐标
            from rich.live import Live

            with Live(
                dashboard.render(), refresh_per_second=2,
                redirect_stdout=True, redirect_stderr=True,
            ) as live:
                while self._alive_workers() > 0:
                    live.update(dashboard.render())
                    time.sleep(0.5)
        else:
            # 事件快照模式（默认）：关键节点打一帧 + 每 30s 一行文字进度
            last_status = time.monotonic()
            while self._alive_workers() > 0:
                if time.monotonic() - last_status >= 30:
                    logger.info("进度 | {}", dashboard.status_line())
                    last_status = time.monotonic()
                time.sleep(0.5)
        self._run_ctx = None

    # ------------------------------------------------------------------ 动态工位

    def _alive_workers(self) -> int:
        with self._wlock:
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            return len(self._worker_threads)

    def _spawn_worker(self) -> None:
        """补开一个工位线程（slot 编号在锁内分配，保证唯一）。"""
        if self._run_ctx is None:
            return
        course, job_queue, dashboard, panel = self._run_ctx
        with self._wlock:
            self._next_slot += 1
            slot = self._next_slot
            t = threading.Thread(
                target=self._slot_worker,
                args=(course, job_queue, dashboard, panel, slot),
                daemon=True,
                name=f"cxauto-worker-{slot}",
            )
            self._worker_threads.append(t)
        t.start()

    def _slot_worker(self, course: Course, job_queue: queue.Queue,
                     dashboard: Dashboard, panel: DashboardLogger | None, slot: int) -> None:
        """一个工位：领任务 -> 刷 -> 歇 10s -> 领下一个，直到队列空或被裁撤。"""
        try:
            self._slot_worker_inner(course, job_queue, dashboard, panel, slot)
        except Exception:  # noqa: BLE001 —— 工位崩溃必须留痕，否则无声消失
            logger.exception("[工位{}] 发生未捕获异常，本工位退出", slot)

    def _slot_worker_inner(self, course: Course, job_queue: queue.Queue,
                           dashboard: Dashboard, panel: DashboardLogger | None, slot: int) -> None:

        def retire() -> None:
            with self._wlock:
                self._worker_threads = [
                    t for t in self._worker_threads if t is not threading.current_thread()
                ]

        first_job = True
        while not self.stop_event.is_set():
            # 运行中调小并行数：多出的工位在安全点自行退出
            if self._alive_workers() > self.target_workers:
                logger.debug("[工位{}] 并行数下调，本工位退出", slot)
                dashboard.retire_slot(slot)
                retire()
                return
            try:
                chapter, job = job_queue.get_nowait()
            except queue.Empty:
                retire()
                return
            if not first_job:
                # 补位间隔：上一个视频刚刷完，歇一下再开工，避免衔接过于整齐
                time.sleep(self.config.slot_gap)
            first_job = False

            title = job.title or job.objectid
            logger.info("[工位{}] 开始: {} ({})", slot, title, chapter.title)
            dashboard.assign(slot, title, chapter.title)
            if panel:
                panel.snapshot(dashboard.render())

            def on_progress(play_seconds: int, total_seconds: int, _slot: int = slot) -> None:
                dashboard.progress(_slot, play_seconds, total_seconds)

            result = self._process_with_retry(course, job, on_progress)
            dashboard.release(slot, result.value)
            if panel:
                panel.snapshot(dashboard.render())
            with self._stats_lock:
                self.stats.add(result)
            logger.info("[工位{}] {}: {}", slot, title, result.value)

    # ------------------------------------------------------------------ 重试

    def _process_with_retry(self, course: Course, job: Job, progress_cb=None) -> StudyResult:
        """单个任务点处理 + 重试。"""
        result = StudyResult.FAILED
        for attempt in range(1, self.config.max_retries + 1):
            if self.stop_event.is_set():
                return StudyResult.SKIPPED
            result = self.study_api.process_job(course, job, progress_cb)
            if result not in RETRYABLE_RESULTS:
                return result
            if attempt < self.config.max_retries:
                logger.debug(
                    "任务 {} 第 {}/{} 次失败({})，{}s 后重试",
                    job.jobid, attempt, self.config.max_retries, result.value,
                    self.config.retry_interval,
                )
                time.sleep(self.config.retry_interval)
        return result
