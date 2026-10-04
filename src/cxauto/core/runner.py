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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from loguru import logger

from ..api.client import ChaoxingClient
from ..api.course import CourseAPI
from ..api.study import StudyAPI, StudyResult
from ..core.config import Config
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

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = ChaoxingClient(config)
        self.course_api = CourseAPI(self.client)
        self.study_api = StudyAPI(self.client, speed=config.speed)
        self.stats = Stats()
        self._stats_lock = threading.Lock()

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

        workers = max(1, min(self.config.concurrency, len(all_jobs)))
        logger.info(
            "任务队列：{} 个视频，{} 个工位同时刷（补位间隔 {}s）",
            len(all_jobs), workers, self.config.slot_gap,
        )

        # 阶段二：工位滚动消费任务队列，主线程驱动进度面板
        job_queue: queue.Queue = queue.Queue()
        for item in all_jobs:
            job_queue.put(item)

        dashboard = Dashboard(course.name, total_jobs=len(all_jobs), slot_count=workers)
        with DashboardLogger() as panel:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(self._slot_worker, course, job_queue, slot, dashboard)
                    for slot in range(workers)
                ]
                while not all(f.done() for f in futures):
                    panel.update(dashboard.render())
                    time.sleep(0.5)

    def _slot_worker(self, course: Course, job_queue: queue.Queue, slot: int,
                     dashboard: Dashboard) -> None:
        """一个工位：领任务 -> 刷 -> 歇 10s -> 领下一个，直到队列空。"""
        first_job = True
        while True:
            try:
                chapter, job = job_queue.get_nowait()
            except queue.Empty:
                return
            if not first_job:
                # 补位间隔：上一个视频刚刷完，歇一下再开工，避免衔接过于整齐
                time.sleep(self.config.slot_gap)
            first_job = False

            title = job.title or job.objectid
            logger.info("[工位{}] 开始: {} (章节{})", slot + 1, title, chapter.index)
            dashboard.assign(slot, title, chapter.index)

            def on_progress(play_seconds: int, total_seconds: int, _slot: int = slot) -> None:
                dashboard.progress(_slot, play_seconds, total_seconds)

            result = self._process_with_retry(course, job, on_progress)
            dashboard.release(slot, result.value)
            with self._stats_lock:
                self.stats.add(result)
            logger.info("[工位{}] {}: {}", slot + 1, title, result.value)

    # ------------------------------------------------------------------ 重试

    def _process_with_retry(self, course: Course, job: Job, progress_cb=None) -> StudyResult:
        """单个任务点处理 + 重试。"""
        result = StudyResult.FAILED
        for attempt in range(1, self.config.max_retries + 1):
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
