"""刷课核心：视频心跳上报、文档与阅读任务完成。

视频刷课采用「真实时间 / 视频时间」双时钟模型：
视频时间按 ``speed`` 倍速快于真实时间流逝，服务端只会看到
上报的 playingTime 平滑推进，不会发现未真实播放。
"""

from __future__ import annotations

import enum
import hashlib
import random
import re
import time

from loguru import logger

from ..core.models import Card, Course, Job
from ..core.ratelimiter import RateLimiter
from . import decode
from .captcha import CaptchaSolver
from .client import ChaoxingClient
from .course import AUDIO_REFERER, MOOC1_BASE, VIDEO_REFERER

# enc 计算的固定盐值（超星前端 JS 硬编码）
ENC_SALT = "d_yHJ!$pdA~5"


class StudyResult(enum.Enum):
    """单个任务点的处理结果。"""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FORBIDDEN = "forbidden"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


def video_enc(clazz_id: str, userid: str, jobid: str, objectid: str,
              playing_time: int, duration: int) -> str:
    """视频日志的 enc 参数。

    官方前端把 8 个字段各用方括号包裹后拼接，整体取 MD5：

    .. code-block:: text

        MD5([clazzId][userid][jobid][objectId][当前进度ms][d_yHJ!$pdA~5][总时长ms][0_总时长])

    clipTime 在前端本是区间数组 ``[0, duration]``，序列化后即 ``0_{duration}``。
    """
    raw = (
        f"[{clazz_id}][{userid}][{jobid}][{objectid}][{playing_time * 1000}]"
        f"[{ENC_SALT}][{duration * 1000}][0_{duration}]"
    )
    return hashlib.md5(raw.encode()).hexdigest()


def knowledge_id_from_otherinfo(otherinfo: str) -> str:
    """从 otherInfo（形如 ``nodeId_12345-cpi_82274641-rt_1d``）提取章节 id。"""
    m = re.search(r"nodeId_(.*?)-", otherinfo)
    return m.group(1) if m else ""


class StudyAPI:
    """任务点完成逻辑。"""

    def __init__(self, client: ChaoxingClient, speed: float = 1.0) -> None:
        self.client = client
        self.speed = speed
        # 视频日志上报对频率极敏感（极易卡验证码），限速 2s + 抖动
        self._log_limiter = RateLimiter(interval=2.0, jitter=2.0)
        self._captcha = CaptchaSolver(client)

    # ------------------------------------------------------------------ 视频

    def get_video_status(self, job: Job) -> dict:
        """拉取视频元信息（dtoken/duration/服务端进度）。"""
        resp = self.client.get(
            f"{MOOC1_BASE}/ananas/status/{job.objectid}",
            params={"k": self.client.fid, "flag": "normal"},
            referer=VIDEO_REFERER,
        )
        return decode.decode_video_status(resp.text)

    def _video_log(self, course: Course, job: Job, status: dict, playing_time: int,
                   isdrag: int, dtype: str = "Video", rt: str = "0.9") -> dict | None:
        """上报一次播放日志。

        isdrag 取值：4 仅用于开局「直接上报看完」的秒过探测；常规心跳与收尾一律用 3
        （与官方播放器一致；实测 isdrag=0 服务端不记账）。

        Returns:
            服务端 JSON（含 isPassed）；风控/异常时返回 None。
        """
        duration = status["duration"]
        enc = video_enc(
            course.clazz_id, self.client.uid, job.jobid, job.objectid, playing_time, duration
        )
        params = {
            "clazzId": course.clazz_id,
            "playingTime": playing_time,
            "duration": duration,
            "clipTime": f"0_{duration}",
            "objectId": job.objectid,
            "otherInfo": job.otherinfo,
            "courseId": course.course_id,
            "jobid": job.jobid,
            "userid": self.client.uid,
            "isdrag": isdrag,
            "view": "pc",
            "enc": enc,
            "dtype": dtype,
            "rt": rt,
            "_t": self.client.timestamp_ms(),
        }
        # 服务端下发的校验字段必须原样回传，缺失会导致进度不被记账
        if job.att_duration:
            params["attDuration"] = job.att_duration
        if job.att_duration_enc:
            params["attDurationEnc"] = job.att_duration_enc
        if job.face_capture_enc:
            params["videoFaceCaptureEnc"] = job.face_capture_enc
        referer = AUDIO_REFERER if dtype == "Audio" else VIDEO_REFERER
        self._log_limiter.wait()
        try:
            resp = self.client.get(
                f"{MOOC1_BASE}/mooc-ans/multimedia/log/a/{course.cpi}/{status['dtoken']}",
                params=params,
                referer=referer,
            )
        except Exception as e:  # noqa: BLE001 —— 网络层异常统一按失败处理
            logger.warning("视频日志上报异常: {}", e)
            return None
        if resp.status_code != 200 or "验证码" in resp.text or "validate" in resp.text:
            logger.warning("视频日志上报被风控 (status={})", resp.status_code)
            return None
        try:
            data = resp.json()
        except ValueError:
            logger.warning("视频日志上报返回非 JSON: {}", resp.text[:200])
            return None
        logger.debug(
            "视频日志上报: isdrag={} playingTime={}s -> isPassed={} (status={})",
            isdrag, playing_time, data.get("isPassed"), data.get("status"),
        )
        return data

    def _rt_value(self, job: Job) -> str:
        """推断上报的 rt 参数：优先 property.rt，其次 otherInfo 的 rt_ 标记。"""
        if "rt" in job.otherinfo:
            m = re.search(r"-rt_([0-9a-zA-Z]+)", job.otherinfo)
            if m:
                return "0.9" if m.group(1) == "d" else m.group(1)
        return "0.9"

    def study_video(self, course: Course, job: Job, progress_cb=None) -> StudyResult:
        """完成一个视频/音频任务点。

        流程：取元信息 -> 先尝试一次「直接上报看完」（isdrag=4）秒过 ->
        未过则进入心跳循环：playingTime 按 speed 倍速推进，随机 30~90s 上报一次
        （isdrag=3），**只有服务端返回 isPassed=true 才算完成**。

        带 videoFaceCaptureEnc 的视频说明课程配置了人脸抓拍（抽检式）：协议中原样
        回传服务端下发的 token。若服务端强制人脸验证则上报不会通过，任务留在原地
        由人工处理；本工具不会伪造任何验证结果。
        """
        if job.face_capture_enc:
            logger.info("该视频配置了人脸抓拍（抽检式），按常规协议尝试: {}", job.title)

        try:
            status = self.get_video_status(job)
        except Exception as e:  # noqa: BLE001
            logger.error("获取视频元信息失败 ({}): {}", job.objectid, e)
            return StudyResult.FAILED

        duration = status["duration"]
        if duration <= 0:
            logger.warning("视频时长为 0，跳过: {}", job.title or job.objectid)
            return StudyResult.SKIPPED

        rt = self._rt_value(job)

        # 第一步：尝试秒过 —— 直接上报「已看完」
        data = self._video_log(course, job, status, duration, isdrag=4, rt=rt)
        if data is not None and data.get("isPassed"):
            logger.success("[秒过] {}", job.title or job.objectid)
            return StudyResult.COMPLETED

        # 第二步：心跳循环。视频时间按 speed 倍速流逝，真实时间原速流逝。
        # 视频任务偶尔以「音频」身份上报才能通过，因此最多尝试两轮（Video -> Audio）。
        dtype = "Video"
        for _round in range(2):
            start = max(job.playtime // 1000, status.get("playtime", 0) // 1000)
            if start >= duration and not job.is_passed:
                # 进度被顶到结尾但任务未通过（如秒过探测留下的记录）：
                # 服务端按累计观看时长放行，必须从头重刷补足
                logger.info("服务端进度已在结尾但未通过，从头重刷: {}", job.title or job.objectid)
                start = 0
            play_time = float(min(start, duration))
            last_log_time = play_time
            wait_time = random.uniform(30, 90)
            last_iter = time.time()
            logger.info(
                "开始刷视频 {} (时长 {}s, 倍速 {}x, 起始 {}s, 身份 {})",
                job.title or job.objectid, duration, self.speed, int(play_time), dtype,
            )
            finished = False
            final_misses = 0  # 播放到结尾后服务端仍未通过的重试次数
            if progress_cb:
                progress_cb(int(play_time), duration)
            while not finished:
                if play_time < duration:
                    time.sleep(1)
                    now = time.time()
                    play_time = min(duration, play_time + (now - last_iter) * self.speed)
                    last_iter = now
                    if progress_cb:
                        progress_cb(int(play_time), duration)
                    # 未到心跳间隔且未播完则继续等待
                    if play_time - last_log_time < wait_time and play_time < duration:
                        continue
                # 到达随机心跳间隔或播放结束：上报一次（isdrag=3）
                data = self._video_log(course, job, status, int(play_time), isdrag=3, rt=rt)
                if data is None:
                    # 风控：稍等、尝试过验证码，然后刷新 dtoken 重来
                    self.client.random_sleep(2, 4)
                    if self._captcha.solve():
                        continue
                    break
                if data.get("isPassed"):
                    finished = True
                    break
                last_log_time = play_time
                wait_time = random.uniform(30, 90)
                if play_time >= duration:
                    # 已到结尾但服务端未放行：稍等后重报，连续多次失败则放弃
                    final_misses += 1
                    logger.debug(
                        "已到视频结尾，等待服务端放行（第 {} 次）", final_misses
                    )
                    if final_misses >= 8:
                        break
                    self.client.random_sleep(3, 6)
            if finished:
                logger.success("[完成] {}", job.title or job.objectid)
                return StudyResult.COMPLETED

            if dtype == "Video":
                logger.info("按 Video 上报未通过，尝试按 Audio 重新上报")
                dtype = "Audio"
            try:
                status = self.get_video_status(job)
            except Exception as e:  # noqa: BLE001
                logger.error("刷新视频元信息失败: {}", e)
                return StudyResult.FORBIDDEN
        logger.warning("视频任务未能完成: {}", job.title or job.objectid)
        return StudyResult.FORBIDDEN

    # ------------------------------------------------------------------ 文档 / 阅读

    def study_document(self, course: Course, job: Job) -> StudyResult:
        """完成文档任务：新协议下是一次性 jtoken 校验请求，无需模拟翻页。"""
        knowledge_id = knowledge_id_from_otherinfo(job.otherinfo)
        if not knowledge_id:
            logger.error("文档任务缺少 nodeId: {}", job.otherinfo)
            return StudyResult.FAILED
        try:
            resp = self.client.get(
                f"{MOOC1_BASE}/ananas/job/document",
                params={
                    "jobid": job.jobid,
                    "knowledgeid": knowledge_id,
                    "courseid": course.course_id,
                    "clazzid": course.clazz_id,
                    "jtoken": job.jtoken,
                    "_dc": self.client.timestamp_ms(),
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("文档任务请求异常: {}", e)
            return StudyResult.FAILED
        if resp.status_code == 200:
            logger.success("[文档] {}", job.title or job.objectid)
            return StudyResult.COMPLETED
        logger.warning("文档任务失败 (status={}): {}", resp.status_code, resp.text[:100])
        return StudyResult.FAILED

    def study_read(self, course: Course, job: Job) -> StudyResult:
        """完成阅读任务：同样是一次性 jtoken 接口。"""
        knowledge_id = knowledge_id_from_otherinfo(job.otherinfo)
        try:
            resp = self.client.get(
                f"{MOOC1_BASE}/ananas/job/readv2",
                params={
                    "jobid": job.jobid,
                    "knowledgeid": knowledge_id,
                    "courseid": course.course_id,
                    "clazzid": course.clazz_id,
                    "jtoken": job.jtoken,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("阅读任务请求异常: {}", e)
            return StudyResult.FAILED
        if resp.status_code == 200:
            logger.success("[阅读] {}", job.title or job.objectid)
            return StudyResult.COMPLETED
        logger.warning("阅读任务失败 (status={}): {}", resp.status_code, resp.text[:100])
        return StudyResult.FAILED

    # ------------------------------------------------------------------ 分发

    def process_job(self, course: Course, job: Job, progress_cb=None) -> StudyResult:
        """按任务类型分发。已完成的任务点直接跳过。

        progress_cb(play_seconds, total_seconds)：视频播放进度回报（面板用）。
        """
        if job.is_passed:
            return StudyResult.SKIPPED
        if not job.jobid or not job.objectid:
            logger.debug("任务点缺少 jobid/objectid，跳过: {}", job)
            return StudyResult.SKIPPED
        if job.type.value == "video":
            return self.study_video(course, job, progress_cb)
        if job.type.value == "document":
            return self.study_document(course, job)
        if job.type.value == "read":
            return self.study_read(course, job)
        return StudyResult.UNUPPORTED

    # 兼容旧调用：卡片级处理在 runner 中按 attachments 逐个分发
    def process_card(self, course: Course, card: Card) -> list[StudyResult]:
        return [self.process_job(course, job) for job in card.attachments]
