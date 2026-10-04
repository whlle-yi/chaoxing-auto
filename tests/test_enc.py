"""enc 算法测试：超星视频日志接口的 MD5 拼接规则。"""

from cxauto.api.study import knowledge_id_from_otherinfo, video_enc

# 已知向量：MD5("[123][456][789][abc][60000][d_yHJ!$pdA~5][300000][0_300]")
KNOWN_VECTOR = "fe7802daf430d62b6cc993753327762a"


def test_video_enc_known_vector():
    assert video_enc("123", "456", "789", "abc", 60, 300) == KNOWN_VECTOR


def test_video_enc_changes_with_playing_time():
    """进度变化必须导致 enc 变化（服务端据此校验参数一致性）。"""
    a = video_enc("1", "2", "3", "4", 10, 100)
    b = video_enc("1", "2", "3", "4", 11, 100)
    assert a != b


def test_video_enc_is_md5_hex():
    result = video_enc("1", "2", "3", "4", 10, 100)
    assert len(result) == 32
    int(result, 16)  # 合法 hex


def test_knowledge_id_from_otherinfo():
    assert knowledge_id_from_otherinfo("nodeId_12345-cpi_82274641-rt_1d") == "12345"
    assert knowledge_id_from_otherinfo("nodeId_999-cpi_1") == "999"
    assert knowledge_id_from_otherinfo("no-match") == ""
