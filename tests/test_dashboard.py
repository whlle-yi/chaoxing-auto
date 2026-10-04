"""进度面板状态逻辑测试。"""

from cxauto.core.dashboard import Dashboard, _fmt_seconds


class TestFmtSeconds:
    def test_minutes(self):
        assert _fmt_seconds(83) == "01:23"

    def test_hours(self):
        assert _fmt_seconds(3661) == "1:01:01"

    def test_negative_clamped(self):
        assert _fmt_seconds(-5) == "00:00"


class TestDashboard:
    def test_assign_and_progress(self):
        d = Dashboard("测试课", total_jobs=3, slot_count=2)
        d.assign(0, "a.mp4", "1.1 标题一")
        d.progress(0, 30, 100)
        slot = d.slots[0]
        assert slot.title == "a.mp4"
        assert slot.play_seconds == 30
        assert slot.total_seconds == 100
        assert d.queue_remaining == 2

    def test_release_counts(self):
        d = Dashboard("测试课", total_jobs=4, slot_count=2)
        d.assign(0, "a.mp4", "1.1 标题一")
        d.release(0, "completed")
        d.assign(1, "b.mp4", "1.2 标题二")
        d.release(1, "forbidden")
        assert d.completed == 1
        assert d.failed == 1
        assert d.slots[0].status == "空闲"

    def test_render_contains_slot_info(self):
        import io

        from rich.console import Console

        d = Dashboard("文化传统与现代文明", total_jobs=9, slot_count=2)
        d.assign(0, "1293.flv", "3.2 科学的内涵随时代的转化")
        d.progress(0, 120, 600)
        panel = d.render()
        assert panel is not None
        console = Console(file=io.StringIO(), width=120, force_terminal=False)
        console.print(panel)
        text = console.file.getvalue()
        assert "3.2 科学的内涵随时代的转化" in text and "1293.flv" in text
        assert "02:00 / 10:00" in text
        assert "排队中 8/9" in text

    def test_two_slots_independent(self):
        d = Dashboard("测试课", total_jobs=2, slot_count=2)
        d.assign(0, "a.mp4", "1.1 标题一")
        d.progress(0, 10, 100)
        assert d.slots[1].status == "空闲"
        assert d.slots[0].status == "播放中"
