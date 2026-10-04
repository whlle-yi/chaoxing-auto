"""风控验证码处理：视频日志接口返回 403 / 要求验证码时自动 OCR。

识别依赖可选依赖 ``ddddocr``，未安装时降级为跳过该任务。
"""

from __future__ import annotations

import random

from loguru import logger

from .client import ChaoxingClient

VERIFY_PNG_URL = "https://mooc1.chaoxing.com/processVerifyPng.ac"
VERIFY_URL = "https://mooc1.chaoxing.com/html/processVerify.ac"


class CaptchaSolver:
    """获取 -> OCR -> 提交验证码；提交后 302 即成功。"""

    def __init__(self, client: ChaoxingClient) -> None:
        self.client = client
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            try:
                import ddddocr
            except ImportError:
                logger.warning(
                    "检测到风控验证码，但未安装 ddddocr（pip install ddddocr），无法自动过验证码"
                )
                return None
            self._ocr = ddddocr.DdddOcr(show_ad=False)
        return self._ocr

    def solve(self, max_attempts: int = 3) -> bool:
        """尝试识别并提交验证码，返回是否成功。"""
        ocr = self._get_ocr()
        if ocr is None:
            return False
        for attempt in range(1, max_attempts + 1):
            resp = self.client.get(f"{VERIFY_PNG_URL}?t={random.random()}")
            if not resp.content:
                continue
            code = ocr.classification(resp.content)
            logger.info("第 {} 次验证码识别结果: {}", attempt, code)
            if not code:
                continue
            # 提交成功时服务端返回 302
            result = self.client.get(f"{VERIFY_URL}?ucode={code}&app=0", timeout=15)
            if result.status_code == 200 and result.url and "processVerify" not in result.url:
                logger.success("验证码通过")
                return True
            self.client.random_sleep(1.0, 2.0)
        logger.error("验证码连续 {} 次未通过", max_attempts)
        return False
