"""Runner 构造回归测试：确保关键属性在 __init__ 中正确初始化。"""

from cxauto.core.config import Config
from cxauto.core.runner import Runner


def _make_runner(tmp_path) -> Runner:
    config = Config(
        username="13800138000",
        password="secret",
        cookie_file=tmp_path / "cookies.txt",
        log_file=tmp_path / "logs" / "test.log",
    )
    return Runner(config)


def test_runner_initializes_stop_event(tmp_path):
    """stop_event 必须先于 StudyAPI 构造完成（GUI 停止按钮依赖它）。"""
    runner = _make_runner(tmp_path)
    assert isinstance(runner.stop_event, type(runner.stop_event))
    assert runner.study_api.stop_event is runner.stop_event


def test_runner_initializes_dashboard_slot(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.dashboard is None
