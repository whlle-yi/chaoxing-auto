"""配置加载：config.ini + 命令行覆盖。"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_SECTION = "common"


@dataclass
class Config:
    """运行配置。

    Attributes:
        username/password: 学习通账号密码。
        course_list: 要刷的课程名列表；为空表示刷全部课程。
        speed: 视频倍速，强制限制在 [1.0, 2.0]，超过 2 倍会触发风控。
        max_retries: 单个任务点的最大重试次数。
        retry_interval: 失败任务的重试间隔（秒）。
        notopen_action: 章节未开放时的处理：``skip`` 跳过 / ``stop`` 停止。
        cookie_file: 登录态持久化文件路径。
        log_file: 运行日志文件路径。
        log_level: 日志级别。
    """

    username: str = ""
    password: str = ""
    course_list: list[str] = field(default_factory=list)
    # 只处理这些类型的任务点，默认仅视频；文档/阅读等设为空串即不启用
    job_types: list[str] = field(default_factory=lambda: ["video"])
    speed: float = 1.0
    max_retries: int = 3
    retry_interval: float = 2.0
    notopen_action: str = "skip"
    cookie_file: Path = Path("cookies.txt")
    log_file: Path = Path("logs/cxauto.log")
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        # 官方前端播放器最多 2 倍速，超速上报极易触发风控
        self.speed = min(2.0, max(1.0, self.speed))

    @classmethod
    def from_ini(cls, path: str | Path) -> "Config":
        """从 ini 文件加载配置。缺失字段用默认值，未设置账号则抛 ValueError。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}（可参考 config.example.ini）")

        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        section = parser[CONFIG_SECTION] if parser.has_section(CONFIG_SECTION) else {}

        username = section.get("username", "").strip()
        password = section.get("password", "").strip()
        if not username or not password:
            raise ValueError("config.ini 中必须填写 username 和 password")

        course_list = [
            name.strip() for name in section.get("course_list", "").split(",") if name.strip()
        ]
        job_types = [
            t.strip().lower()
            for t in section.get("job_types", "video").split(",")
            if t.strip()
        ]
        return cls(
            username=username,
            password=password,
            course_list=course_list,
            job_types=job_types,
            speed=section.getfloat("speed", fallback=1.0),
            max_retries=section.getint("max_retries", fallback=3),
            retry_interval=section.getfloat("retry_interval", fallback=2.0),
            notopen_action=section.get("notopen_action", fallback="skip").strip().lower(),
            cookie_file=Path(section.get("cookie_file", fallback="cookies.txt").strip()),
            log_file=Path(section.get("log_file", fallback="logs/cxauto.log").strip()),
            log_level=section.get("log_level", fallback="INFO").strip().upper(),
        )
