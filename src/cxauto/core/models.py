"""数据模型：账号、课程、章节、任务点。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class Account:
    """学习通账号（手机号/学号 + 密码）。"""

    username: str
    password: str


class JobType(str, Enum):
    """任务点类型。

    超星 attachments 中的 type 字段：
    ``video`` 视频 / ``document`` 文档 / ``workid`` 测验 / ``read`` 阅读 / 直播需按 property 识别。
    """

    VIDEO = "video"
    DOCUMENT = "document"
    WORK = "workid"
    READ = "read"
    LIVE = "live"
    UNKNOWN = "unknown"

    @classmethod
    def from_attachment(cls, attachment: dict) -> "JobType":
        """从 attachment 原始字典识别任务类型。"""
        att_type = str(attachment.get("type", "")).lower()
        prop = attachment.get("property") or {}
        if "liveid" in prop or "streamName" in prop or "vdoid" in prop:
            return cls.LIVE
        if att_type in ("video", "document", "workid", "read"):
            return cls(att_type)
        return cls.UNKNOWN


@dataclass
class Course:
    """一门课程。cpi 是后续所有接口的必备参数。"""

    course_id: str
    clazz_id: str
    cpi: str
    name: str = ""
    teacher: str = ""


@dataclass
class Chapter:
    """一个章节（knowledge card 的上层单位）。"""

    index: int
    knowledge_id: str
    title: str
    job_count: int = 1
    has_finished: bool = False
    need_unlock: bool = False


@dataclass
class Job:
    """一个任务点（attachment）。"""

    type: JobType
    jobid: str = ""
    objectid: str = ""
    title: str = ""
    otherinfo: str = ""
    enc: str = ""
    jtoken: str = ""
    aid: str = ""
    mid: str = ""
    # 视频类
    playtime: int = 0  # 毫秒，服务端记录的已看进度
    att_duration: int = 0  # 服务端下发的累计观看时长（毫秒）
    att_duration_enc: str = ""  # attDuration 的服务端校验码
    face_capture_enc: str = ""  # 人脸抓拍校验（有值说明该视频要求人脸，无法自动完成）
    # isPassed 为 true 的任务点无需处理
    is_passed: bool = False

    @classmethod
    def from_attachment(cls, attachment: dict) -> "Job":
        """把 mArg.attachments 中的一项规范化为 Job。

        注意：objectid 可能在顶层 ``objectId``/``objectid``，文档类在 ``property.objectid``。
        """
        prop = attachment.get("property") or {}
        objectid = (
            attachment.get("objectId")
            or attachment.get("objectid")
            or prop.get("objectid")
            or ""
        )
        # 超星接口会根据 otherInfo 是否携带 courseId 改变 URL 拼接方式，统一去掉 & 之后的内容
        otherinfo = str(attachment.get("otherInfo") or "").split("&")[0]
        playtime_ms = attachment.get("playTime") or 0
        att_duration = attachment.get("attDuration") or 0
        return cls(
            type=JobType.from_attachment(attachment),
            jobid=str(attachment.get("jobid") or ""),
            objectid=str(objectid),
            title=str(prop.get("title") or prop.get("name") or attachment.get("title") or ""),
            otherinfo=otherinfo,
            enc=str(attachment.get("enc") or ""),
            jtoken=str(attachment.get("jtoken") or ""),
            aid=str(attachment.get("aid") or ""),
            mid=str(attachment.get("mid") or ""),
            playtime=int(playtime_ms) if playtime_ms else 0,
            att_duration=int(att_duration) if att_duration else 0,
            att_duration_enc=str(attachment.get("attDurationEnc") or ""),
            face_capture_enc=str(attachment.get("videoFaceCaptureEnc") or ""),
            is_passed=bool(attachment.get("isPassed")),
        )


@dataclass
class CardDefaults:
    """mArg.defaults：卡片级公共参数。"""

    ktoken: str = ""
    mt_enc: str = ""
    report_time_interval: int = 60
    defenc: str = ""
    cardid: str = ""
    cpi: str = ""
    qnenc: str = ""
    knowledgeid: str = ""
    report_url: str = ""  # 日志上报路径（不含主机名），如 mooc-ans/multimedia/log/a/{cpi}


@dataclass
class Card:
    """一张任务卡片：defaults + attachments。"""

    defaults: CardDefaults = field(default_factory=CardDefaults)
    attachments: list[Job] = field(default_factory=list)
