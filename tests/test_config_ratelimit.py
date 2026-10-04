"""限速器与配置加载测试。"""

import time

import pytest

from cxauto.core.config import Config
from cxauto.core.ratelimiter import RateLimiter


class TestRateLimiter:
    def test_enforces_interval(self):
        limiter = RateLimiter(interval=0.2)
        start = time.monotonic()
        limiter.wait()
        limiter.wait()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.2

    def test_no_wait_when_interval_passed(self):
        limiter = RateLimiter(interval=0.05)
        limiter.wait()
        time.sleep(0.08)
        start = time.monotonic()
        limiter.wait()
        assert time.monotonic() - start < 0.05


class TestConfig:
    def _write(self, tmp_path, content):
        path = tmp_path / "config.ini"
        path.write_text(content, encoding="utf-8")
        return path

    def test_from_ini(self, tmp_path):
        path = self._write(tmp_path, """
[common]
username = 13800138000
password = secret
course_list = 高等数学, 大学英语
speed = 1.5
max_retries = 5
notopen_action = stop
""")
        config = Config.from_ini(path)
        assert config.username == "13800138000"
        assert config.course_list == ["高等数学", "大学英语"]
        assert config.speed == 1.5
        assert config.max_retries == 5
        assert config.notopen_action == "stop"

    def test_speed_clamped_to_2(self, tmp_path):
        path = self._write(tmp_path, "[common]\nusername=u\npassword=p\nspeed=5\n")
        assert Config.from_ini(path).speed == 2.0

    def test_speed_floor_1(self, tmp_path):
        path = self._write(tmp_path, "[common]\nusername=u\npassword=p\nspeed=0.2\n")
        assert Config.from_ini(path).speed == 1.0

    def test_missing_account_raises(self, tmp_path):
        path = self._write(tmp_path, "[common]\nusername=\npassword=\n")
        with pytest.raises(ValueError):
            Config.from_ini(path)

    def test_concurrency_default_and_parse(self, tmp_path):
        path = self._write(tmp_path, "[common]\nusername=u\npassword=p\nconcurrency=3\n")
        config = Config.from_ini(path)
        assert config.concurrency == 3
        path2 = self._write(tmp_path, "[common]\nusername=u\npassword=p\n")
        assert Config.from_ini(path2).concurrency == 1  # 默认串行

    def test_concurrency_hard_capped_at_3(self, tmp_path):
        """并发上限 3 在配置层强制，手写多大都没用。"""
        path = self._write(tmp_path, "[common]\nusername=u\npassword=p\nconcurrency=10\n")
        assert Config.from_ini(path).concurrency == 3

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config.from_ini(tmp_path / "nope.ini")
