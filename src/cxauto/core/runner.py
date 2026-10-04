"""任务调度：登录 -> 课程 -> 章节 -> 任务点，串行推进并带重试。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from loguru import logger
from tqdm import tqdm

from ..api.client import ChaoxingClient
from ..api.course import CourseAPI
from ..api.study import StudyAPI, StudyResult
from ..core.config import Config
from ..core.models import Card, Chapter, Course, Job

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
    """刷课主流程。串行推进（对服务端最友好），失败任务按配置重试。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = ChaoxingClient(config)
        self.course_api = CourseAPI(self.client)
        self.study_api = StudyAPI(self.client, speed=config.speed)
        self.stats = Stats()

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

    def _run_course(self, course: Course) -> None:
        chapters = self.course_api.get_chapter_list(course)
        pending = [
            ch for ch in chapters
            if not ch.has_finished and not (ch.need_unlock and self.config.notopen_action == "skip")
        ]
        logger.info("待处理章节 {}/{}", len(pending), len(chapters))

        for ch in pending:
            if ch.need_unlock:
                if self.config.notopen_action == "stop":
                    logger.info("章节 {} 未开放，按配置停止本课程", ch.index)
                    return
                logger.debug("章节 {} 未开放，跳过", ch.index)
                continue
            self._run_chapter(course, ch)

    def _run_chapter(self, course: Course, chapter: Chapter) -> None:
        """处理一个章节：拉卡片 -> 逐个处理任务点（带重试）。"""
        cards = self.course_api.get_cards(course, chapter)
        jobs: list[tuple[Card, Job]] = []
        for card in cards:
            for job in card.attachments:
                if not job.is_passed:
                    jobs.append((card, job))
        if not jobs:
            logger.debug("章节 {} 无待处理任务点", chapter.title)
            return

        desc = f"课程[{course.name}] 章节{chapter.index}"
        with tqdm(total=len(jobs), desc=desc, unit="任务", leave=False) as bar:
            for card, job in jobs:
                result = self._process_with_retry(course, job)
                self.stats.add(result)
                label = (job.title or job.objectid or job.jobid)[:24]
                bar.set_postfix_str(f"{label} -> {result.value}")
                bar.update(1)
                self.client.random_sleep(0.3, 1.0)

    def _process_with_retry(self, course: Course, job: Job) -> StudyResult:
        """单个任务点处理 + 重试。"""
        result = StudyResult.FAILED
        for attempt in range(1, self.config.max_retries + 1):
            result = self.study_api.process_job(course, job)
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
