"""HTML/JSON 解析测试：使用贴近真实页面的最小样例。"""

import pytest

from cxauto.api import decode
from cxauto.core.models import JobType


COURSE_LIST_HTML = """
<div class="course">
    <input type="hidden" name="courseId" value="200001">
    <input type="hidden" name="clazzId" value="300001">
    <a href="https://mooc1.chaoxing.com/visit/stucoursemiddle?courseid=200001&clazzid=300001&cpi=82274641&ismooc2=1" target="_blank">
        <span class="course-name" title="高等数学">高等数学</span>
    </a>
    <p class="margint10" title="张老师">张老师</p>
</div>
<div class="course">
    <input type="hidden" name="courseId" value="200002">
    <input type="hidden" name="clazzId" value="300002">
    <a class="not-open-tip" href="#">课程未开放</a>
</div>
"""

CHAPTER_HTML = """
<div class="chapter_unit">
    <div id="cur10001">
        <h3>第一章 函数与极限</h3>
        <input class="knowledgeJobCount" type="hidden" value="3">
        <span class="bntHoverTips">已完成</span>
    </div>
    <div id="cur10002">
        <h3>第二章 导数</h3>
        <span class="bntHoverTips">任务点未解锁</span>
    </div>
</div>
"""

CARD_HTML = """
<script>
try {
    if (getCookieWithPath("view", "true") == "true") {}
    var mArg = {"defaults":{"ktoken":"k123","mtEnc":"mt123","reportTimeInterval":60,
        "defenc":"def123","cardid":"card1","cpi":"82274641","qnenc":"qn123",
        "knowledgeid":"10001"},
        "attachments":[{"type":"video","jobid":"111","objectId":"obj-aaa","enc":"e1",
            "otherInfo":"nodeId_10001-cpi_82274641-rt_1d","isPassed":false,"playTime":30000,
            "property":{"title":"第一节","rt":"0.9"}},
            {"type":"document","jobid":"222","property":{"objectid":"obj-bbb","title":"课件.pdf"},
            "jtoken":"tok","otherInfo":"nodeId_10001-cpi_82274641","isPassed":true}]};
} catch(e){}
</script>
"""


class TestCourseList:
    def test_decode(self):
        courses = decode.decode_course_list(COURSE_LIST_HTML)
        assert len(courses) == 1  # 未开放课程被跳过
        c = courses[0]
        assert c.course_id == "200001"
        assert c.clazz_id == "300001"
        assert c.cpi == "82274641"
        assert "高等数学" in c.name

    def test_empty_html(self):
        assert decode.decode_course_list("<div></div>") == []


class TestChapterList:
    def test_decode(self):
        chapters = decode.decode_chapter_list(CHAPTER_HTML)
        assert [ch.knowledge_id for ch in chapters] == ["10001", "10002"]
        assert chapters[0].job_count == 3
        assert chapters[0].has_finished is True
        assert chapters[0].need_unlock is False
        assert chapters[1].need_unlock is True

    def test_missing_job_count_defaults_to_1(self):
        html = '<div class="chapter_unit"><div id="cur5"><h3>x</h3></div></div>'
        chapters = decode.decode_chapter_list(html)
        assert chapters[0].job_count == 1


class TestCard:
    def test_decode(self):
        card = decode.decode_card(CARD_HTML)
        assert card is not None
        assert card.defaults.knowledgeid == "10001"
        assert card.defaults.report_time_interval == 60
        assert len(card.attachments) == 2

        video, doc = card.attachments
        assert video.type is JobType.VIDEO
        assert video.objectid == "obj-aaa"
        assert video.otherinfo == "nodeId_10001-cpi_82274641-rt_1d"
        assert video.playtime == 30000
        assert doc.type is JobType.DOCUMENT
        assert doc.objectid == "obj-bbb"  # objectid 在 property 里
        assert doc.is_passed is True

    def test_no_marg_returns_none(self):
        assert decode.decode_card("<html>plain page</html>") is None

    def test_broken_json_returns_none(self):
        assert decode.decode_card("<script>var mArg = {broken; </script>") is None


class TestVideoStatus:
    def test_decode(self):
        data = decode.decode_video_status(
            '{"status":"success","dtoken":"dt9","duration":600,"crc":"c","key":"k","playTime":120000}'
        )
        assert data["dtoken"] == "dt9"
        assert data["duration"] == 600
        assert data["playtime"] == 120000

    def test_failure_raises(self):
        with pytest.raises(ValueError):
            decode.decode_video_status('{"status":"error"}')
