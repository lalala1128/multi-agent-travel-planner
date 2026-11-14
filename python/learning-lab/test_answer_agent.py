from unittest.mock import patch

from answer_agent import AnswerAgent

import httpx
import pytest

from schemas import KnowledgeChunk
def test_no_knowledge_skips_model():
    agent = AnswerAgent()

    with patch("answer_agent.httpx.Client") as mock_client:
        result = agent.run(
            question="有什么美食建议？",
            chunks=[],
        )

        mock_client.assert_not_called()

    assert result.citations == []
    assert "资料不足" in result.answer
def test_reject_unknown_citation(monkeypatch):
    # 使用测试密钥，测试结束后自动恢复环境变量
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    agent = AnswerAgent()

    # 本次检索只提供这一条资料
    chunk = KnowledgeChunk(
        id="real-1",
        city="首尔",
        source="首尔.md",
        chunk_index=1,
        text="可以将当地市场探索与街区游览结合安排。",
        score=0.9,
    )

    # 模拟模型返回：结构正确，但引用不存在
    def fake_deepseek(request):
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"answer":"可以体验当地市场",'
                                '"citations":["fake-1"]}'
                            ),
                        },
                    },
                ],
            },
        )

    fake_client = httpx.Client(
        transport=httpx.MockTransport(fake_deepseek),
    )

    with patch(
        "answer_agent.httpx.Client",
        return_value=fake_client,
    ):
        with pytest.raises(ValueError, match="不存在"):
            agent.run(
                question="有什么美食体验？",
                chunks=[chunk],
            )