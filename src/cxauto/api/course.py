"""课程 / 章节 / 任务卡片抓取。"""

from __future__ import annotations

from loguru import logger

from ..core.models import Card, Chapter, Course
from . import decode
from .client import ChaoxingClient

MOOC_BASE = "https://mooc2-ans.chaoxing.com/mooc2-ans"
MOOC1_BASE = "https://mooc1.chaoxing.com"
# courselistdata 接口需要特定 Referer，否则返回空
COURSE_LIST_REFERER = (
    "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
    "?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans"
)
VIDEO_REFERER = "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2025-0725-1842"
AUDIO_REFERER = "https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=2025-0725-1842"


class CourseAPI:
    """课程、章节、任务卡片的抓取与解析。"""

    def __init__(self, client: ChaoxingClient) -> None:
        self.client = client

    # ------------------------------------------------------------------ 课程

    def get_course_list(self, name_filter: list[str] | None = None) -> list[Course]:
        """拉取全部课程，可选按名称过滤。"""
        courses: list[Course] = []
        resp = self.client.post(
            f"{MOOC_BASE}/visit/courselistdata",
            data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
            referer=COURSE_LIST_REFERER,
        )
        courses.extend(decode.decode_course_list(resp.text))

        # 课程可能被归入文件夹，二级目录需要逐个请求
        interaction = self.client.get(
            f"{MOOC_BASE}/visit/interaction", referer=COURSE_LIST_REFERER
        )
        for folder_id, folder_name in decode.decode_folder_list(interaction.text):
            logger.debug("扫描课程文件夹: {}", folder_name)
            resp = self.client.post(
                f"{MOOC_BASE}/visit/courselistdata",
                data={
                    "courseType": 1,
                    "courseFolderId": folder_id,
                    "query": "",
                    "superstarClass": 0,
                },
                referer=COURSE_LIST_REFERER,
            )
            courses.extend(decode.decode_course_list(resp.text))

        # 去重（同一课程可能同时出现在一级和二级目录）
        unique: dict[tuple[str, str], Course] = {}
        for course in courses:
            unique.setdefault((course.course_id, course.clazz_id), course)
        courses = list(unique.values())

        if name_filter:
            # 子串匹配：课程名可能带学期/学校后缀，按精确名过滤容易漏
            courses = [c for c in courses if any(f in c.name for f in name_filter)]
        logger.info("共获取 {} 门课程", len(courses))
        return courses

    # ------------------------------------------------------------------ 章节

    def get_chapter_list(self, course: Course) -> list[Chapter]:
        """拉取课程章节列表。"""
        resp = self.client.get(
            f"{MOOC_BASE}/mycourse/studentcourse",
            params={
                "courseid": course.course_id,
                "clazzid": course.clazz_id,
                "cpi": course.cpi,
                "ut": "s",
            },
            referer=COURSE_LIST_REFERER,
        )
        chapters = decode.decode_chapter_list(resp.text)
        logger.info("课程《{}》共 {} 个章节", course.name, len(chapters))
        return chapters

    # ------------------------------------------------------------------ 卡片

    def get_cards(self, course: Course, chapter: Chapter) -> list[Card]:
        """抓取一个章节下的全部任务卡片。

        一个章节可能有多张卡片（视频页/文档页/测验页各一张），接口需要按
        num=0..6 穷举请求，少一张都会导致章节任务不完整。
        """
        cards: list[Card] = []
        for num in range(7):
            resp = self.client.get(
                f"{MOOC1_BASE}/mooc-ans/knowledge/cards",
                params={
                    "clazzid": course.clazz_id,
                    "courseid": course.course_id,
                    "knowledgeid": chapter.knowledge_id,
                    "ut": "s",
                    "cpi": course.cpi,
                    "v": "2025-0424-1038-3",
                    "mooc2": 1,
                    "num": num,
                },
                referer=COURSE_LIST_REFERER,
            )
            if "章节未开放" in resp.text:
                logger.debug("章节 {} 未开放", chapter.knowledge_id)
                break
            card = decode.decode_card(resp.text)
            if card is None:
                break
            cards.append(card)
            self.client.random_sleep(0.0, 0.2)
        logger.debug("章节 {} 解析出 {} 张卡片", chapter.knowledge_id, len(cards))
        return cards
