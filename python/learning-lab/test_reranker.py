import pytest

from reranker import keyword_score, rerank


def test_keyword_rerank_can_promote_more_direct_evidence():
    candidates = [
        {"id": "history", "text": "历史街区适合慢步游览。", "score": 0.70},
        {"id": "food", "text": "当地美食体验可以安排市场探访。", "score": 0.65},
    ]

    ranked = rerank("当地美食体验有什么建议？", candidates, keyword_weight=0.2)

    assert ranked[0]["id"] == "food"
    assert ranked[0]["vector_score"] == 0.65
    assert ranked[0]["keyword_score"] > 0
    assert keyword_score("美食", "天气提醒") == 0


def test_keyword_weight_is_validated():
    with pytest.raises(ValueError):
        rerank("问题", [], keyword_weight=1.1)
