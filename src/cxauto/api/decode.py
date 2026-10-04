"""HTML/JSON 解析：超星页面上的数据全部靠正则 + BeautifulSoup 提取。

超星改版时通常只需要修改本模块，请求层不受影响。
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..core.models import Card, CardDefaults, Chapter, Course, Job


def decode_course_list(html: str) -> list[Course]:
    """解析课程列表页（``visit/courselistdata`` 返回的 HTML 片段）。"""
    soup = BeautifulSoup(html, "html.parser")
    courses: list[Course] = []
    for div in soup.select("div.course"):
        # 未开放课程直接跳过
        if div.select_one("a.not-open-tip") or div.select_one("div.not-open-tip"):
            continue
        course_id = _input_value(div, "courseId")
        clazz_id = _input_value(div, "clazzId")
        if not course_id or not clazz_id:
            continue
        # cpi 藏在课程链接的 href 里
        cpi = ""
        link = div.select_one("a[href]")
        if link and link.get("href"):
            m = re.search(r"cpi=(\d+)", str(link["href"]))
            if m:
                cpi = m.group(1)
        # 课程名优先取 span.course-name（带 title 属性），旧版页面回退到 div.title/text
        name = ""
        name_span = div.select_one("span.course-name")
        if name_span:
            name = (name_span.get("title") or name_span.get_text(strip=True)).strip()
        if not name:
            name = div.get("title", "").strip() or div.get_text(" ", strip=True)[:50]
        teacher_el = div.select_one("p.margint10")
        courses.append(
            Course(
                course_id=course_id,
                clazz_id=clazz_id,
                cpi=cpi,
                name=name,
                teacher=(teacher_el.get("title", "").strip() if teacher_el else ""),
            )
        )
    return courses


def decode_folder_list(html: str) -> list[tuple[str, str]]:
    """解析课程文件夹列表，返回 [(folder_id, folder_name), ...]。"""
    soup = BeautifulSoup(html, "html.parser")
    folders: list[tuple[str, str]] = []
    for li in soup.select("ul.file-list > li"):
        file_id = li.get("fileid")
        if file_id:
            folders.append((str(file_id), li.get_text(" ", strip=True)[:50]))
    return folders


def clean_chapter_title(raw: str) -> str:
    """把章节 div 的原始文本清洗成「1.1 标题」形式。

    原始文本形如 ``1.1 国内外传统文化理论 1 1个待完成任务点``，去掉任务点计数等杂质。
    """
    text = raw.split("待完成任务点")[0]
    text = re.sub(r"[\s\d]+$", "", text)
    for marker in ("已完成", "任务点未解锁"):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip()


def decode_chapter_list(html: str) -> list[Chapter]:
    """解析章节列表页（``mycourse/studentcourse``）。

    每个章节 ``div`` 的 id 形如 ``cur123456``，去 ``cur`` 前缀即 knowledgeid。
    """
    soup = BeautifulSoup(html, "html.parser")
    chapters: list[Chapter] = []
    index = 0
    for unit in soup.select("div.chapter_unit"):
        for div in unit.find_all("div", id=re.compile(r"^cur\d+$")):
            knowledge_id = re.sub(r"^cur", "", div["id"])
            title_el = div.select_one("span.bntHoverTips")
            tips_text = title_el.get_text(strip=True) if title_el else ""
            job_count_input = div.select_one("input.knowledgeJobCount")
            try:
                job_count = int(job_count_input.get("value", "1")) if job_count_input else 1
            except ValueError:
                job_count = 1
            index += 1
            chapters.append(
                Chapter(
                    index=index,
                    knowledge_id=knowledge_id,
                    title=clean_chapter_title(div.get_text(" ", strip=True)),
                    job_count=job_count,
                    need_unlock="解锁" in tips_text,
                    has_finished="已完成" in tips_text,
                )
            )
    return chapters


def decode_card(html: str) -> Card | None:
    """从任务卡片页面提取内嵌的 ``mArg = {...};`` JSON 并解析。

    Returns:
        解析成功返回 Card；页面没有 mArg（无任务/非任务卡片）返回 None。
    """
    matches = re.findall(r"mArg=\{(.*?)\};", html.replace(" ", ""), flags=re.S)
    if not matches:
        return None
    try:
        data = json.loads("{" + matches[0] + "}")
    except json.JSONDecodeError:
        return None

    defaults_raw = data.get("defaults") or {}
    defaults = CardDefaults(
        ktoken=str(defaults_raw.get("ktoken", "")),
        mt_enc=str(defaults_raw.get("mtEnc", "")),
        report_time_interval=int(defaults_raw.get("reportTimeInterval") or 60),
        defenc=str(defaults_raw.get("defenc", "")),
        cardid=str(defaults_raw.get("cardid", "")),
        cpi=str(defaults_raw.get("cpi", "")),
        qnenc=str(defaults_raw.get("qnenc", "")),
        knowledgeid=str(defaults_raw.get("knowledgeid", "")),
        report_url=str(defaults_raw.get("reportUrl", "")),
    )
    attachments = [Job.from_attachment(att) for att in data.get("attachments") or []]
    return Card(defaults=defaults, attachments=attachments)


def decode_video_status(json_text: str) -> dict:
    """解析 ``ananas/status/{objectid}`` 的 JSON，校验 status == success。"""
    data = json.loads(json_text)
    if data.get("status") != "success":
        raise ValueError(f"视频元信息获取失败: {data}")
    return {
        "dtoken": str(data.get("dtoken", "")),
        "duration": int(data.get("duration") or 0),
        "crc": str(data.get("crc", "")),
        "key": str(data.get("key", "")),
        "playtime": int(data.get("playTime") or 0),
    }


def _input_value(soup_node, name: str) -> str:
    """取节点内 ``<input name=...>`` 的 value。"""
    el = soup_node.find("input", attrs={"name": name})
    if el and el.get("value"):
        return str(el["value"]).strip()
    return ""
