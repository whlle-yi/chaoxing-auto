"""超星客户端：会话管理、登录、Cookie 持久化、公共请求封装。"""

from __future__ import annotations

import random
import re
import threading
from pathlib import Path

import requests
from loguru import logger

from ..core.config import Config
from ..core.models import Account
from . import cipher

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

LOGIN_URL = "https://passport2.chaoxing.com/fanyalogin"


class NotLoggedInError(Exception):
    """登录态失效（Cookie 缺失或被服务端踢回登录页）。"""


class ChaoxingClient:
    """负责与超星服务端的底层交互。

    - 登录：POST ``fanyalogin``，用户名/密码 AES-CBC 加密；
    - 登录态持久化：把 Cookie 存到本地文件，下次运行优先复用；
    - 失效自愈：请求被重定向到登录页时自动重登（线程安全）。
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.account = Account(username=config.username, password=config.password)
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)
        self.session.mount(
            "https://",
            requests.adapters.HTTPAdapter(max_retries=requests.adapters.Retry(total=10, backoff_factor=0.5)),
        )
        self._login_lock = threading.Lock()
        self._uid: str = ""
        self._fid: str = ""
        self._load_cookies()

    # ------------------------------------------------------------------ 登录

    def login(self, force: bool = False) -> None:
        """登录并保存 Cookie。已有有效 Cookie 时跳过，除非 ``force=True``。"""
        if not force and self.check_session():
            logger.info("本地 Cookie 有效，跳过登录（uid={}）", self._uid)
            return
        with self._login_lock:
            if not force and self.check_session():
                return
            self._fanya_login()

    def _fanya_login(self) -> None:
        """密码登录。失败时抛出 RuntimeError，msg2 为服务端返回的错误信息。"""
        logger.info("使用账号密码登录: {}", self._mask(self.account.username))
        resp = self.session.post(
            LOGIN_URL,
            data={
                "fid": "-1",
                "uname": cipher.encrypt(self.account.username),
                "password": cipher.encrypt(self.account.password),
                "refer": "https%3A%2F%2Fi.chaoxing.com",
                "t": True,
                "forbidotherlogin": 0,
                "validate": "",
                "doubleFactorLogin": 0,
                "independentId": 0,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("status"):
            self._uid = self._cookie("_uid") or self._cookie("UID") or ""
            self._fid = self._cookie("fid") or ""
            self._save_cookies()
            logger.success("登录成功 (uid={}, fid={})", self._uid, self._fid or "unknown")
        else:
            raise RuntimeError(f"登录失败: {data.get('msg2', data)}")

    def check_session(self) -> bool:
        """校验登录态：必须有 _uid，且课程接口不返回登录页。"""
        if not self._uid:
            return False
        try:
            resp = self.session.post(
                "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata",
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                headers={"Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"},
                timeout=10,
            )
            text = resp.text
        except requests.RequestException as e:
            logger.warning("登录态校验请求异常: {}", e)
            return False
        if "passport2.chaoxing.com" in text or "login" in resp.url:
            return False
        return True

    # ------------------------------------------------------------------ Cookie

    def _save_cookies(self) -> None:
        path = Path(self.config.cookie_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{c.name}={c.value}" for c in self.session.cookies]
        path.write_text("; ".join(lines), encoding="utf-8")
        logger.debug("Cookie 已保存到 {}", path)

    def _load_cookies(self) -> None:
        path = Path(self.config.cookie_file)
        if not path.exists():
            return
        for pair in path.read_text(encoding="utf-8").split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, _, value = pair.partition("=")
                self.session.cookies.set(name.strip(), value.strip())
        self._uid = self._cookie("_uid") or self._cookie("UID") or ""
        self._fid = self._cookie("fid") or ""
        if self._uid:
            logger.debug("已从 {} 恢复 Cookie (uid={})", path, self._uid)

    def _cookie(self, name: str) -> str:
        return self.session.cookies.get(name, domain=".chaoxing.com") or ""

    # ------------------------------------------------------------------ 请求封装

    def get(self, url: str, *, referer: str = "", timeout: int = 10, **kwargs) -> requests.Response:
        """GET 请求；被重定向到登录页时自动重登后重试一次。"""
        headers = kwargs.pop("headers", {})
        if referer:
            headers["Referer"] = referer
        resp = self.session.get(url, timeout=timeout, headers=headers or None, **kwargs)
        if self._hit_login_page(resp):
            logger.warning("登录态失效，自动重新登录")
            self.login(force=True)
            resp = self.session.get(url, timeout=timeout, headers=headers or None, **kwargs)
        return resp

    def post(self, url: str, *, referer: str = "", timeout: int = 10, **kwargs) -> requests.Response:
        """POST 请求；被重定向到登录页时自动重登后重试一次。"""
        headers = kwargs.pop("headers", {})
        if referer:
            headers["Referer"] = referer
        resp = self.session.post(url, timeout=timeout, headers=headers or None, **kwargs)
        if self._hit_login_page(resp):
            logger.warning("登录态失效，自动重新登录")
            self.login(force=True)
            resp = self.session.post(url, timeout=timeout, headers=headers or None, **kwargs)
        return resp

    @staticmethod
    def _hit_login_page(resp: requests.Response) -> bool:
        return "passport2.chaoxing.com" in resp.url or "login" in resp.url

    # ------------------------------------------------------------------ 杂项

    @property
    def uid(self) -> str:
        if not self._uid:
            raise NotLoggedInError("尚未登录或 Cookie 中缺少 _uid")
        return self._uid

    @property
    def fid(self) -> str:
        return self._fid or "1024"

    @staticmethod
    def timestamp_ms() -> int:
        """毫秒时间戳（缓存穿透参数 _t）。"""
        import time

        return int(time.time() * 1000)

    @staticmethod
    def _mask(text: str) -> str:
        """账号脱敏用于日志输出。"""
        if len(text) <= 4:
            return "****"
        return text[:3] + "****" + text[-2:]

    @staticmethod
    def random_sleep(low: float, high: float) -> None:
        """随机小憩，模拟人工节奏。"""
        import time

        time.sleep(random.uniform(low, high))
