from unittest.mock import call, patch

import httpx
import pytest
from pydantic import ValidationError

from answer_agent import AnswerAgent
from schemas import KnowledgeChunk


@pytest.fixture
def evidence(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    return KnowledgeChunk(
        id="real-1",
        city="首尔",
        source="首尔.md",
        chunk_index=1,
        text="可以体验当地市场。",
        score=0.9,
    )


def successful_response():
    return httpx.Response(
        200,
        json={
            "choices": [{
                "message": {
                    "content": '{"answer":"可以体验当地市场","citations":["real-1"]}',
                },
            }],
        },
    )


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_error_then_success(evidence, error_type):
    attempts = []
    retries = []

    def fake_deepseek(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise error_type("模拟连接失败或超时", request=request)
        return successful_response()

    fake_client = httpx.Client(transport=httpx.MockTransport(fake_deepseek))
    with (
        patch("answer_agent.httpx.Client", return_value=fake_client),
        patch("answer_agent.time.sleep") as sleep,
    ):
        result = AnswerAgent().run(
            "有什么建议？",
            [evidence],
            on_retry=lambda attempt, error: retries.append((attempt, type(error).__name__)),
        )

    assert result.citations == ["real-1"]
    assert len(attempts) == 2
    assert retries == [(2, error_type.__name__)]
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_failure_stops_after_three_attempts(evidence, error_type):
    attempts = []

    def fake_deepseek(request):
        attempts.append(1)
        raise error_type("模拟持续连接失败或超时", request=request)

    fake_client = httpx.Client(transport=httpx.MockTransport(fake_deepseek))
    with (
        patch("answer_agent.httpx.Client", return_value=fake_client),
        patch("answer_agent.time.sleep") as sleep,
    ):
        with pytest.raises(error_type):
            AnswerAgent().run("有什么建议？", [evidence])

    assert len(attempts) == 3
    assert sleep.call_args_list == [call(1), call(2)]


def test_authentication_failure_is_not_retried(evidence):
    attempts = []

    def fake_deepseek(request):
        attempts.append(1)
        return httpx.Response(401, json={"error": "模拟无效密钥"})

    fake_client = httpx.Client(transport=httpx.MockTransport(fake_deepseek))
    with (
        patch("answer_agent.httpx.Client", return_value=fake_client),
        patch("answer_agent.time.sleep") as sleep,
    ):
        with pytest.raises(httpx.HTTPStatusError) as error:
            AnswerAgent().run("有什么建议？", [evidence])

    assert error.value.response.status_code == 401
    assert len(attempts) == 1
    sleep.assert_not_called()


def test_invalid_answer_json_is_not_retried(evidence):
    attempts = []

    def fake_deepseek(request):
        attempts.append(1)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "这不是 JSON"}}]},
        )

    fake_client = httpx.Client(transport=httpx.MockTransport(fake_deepseek))
    with (
        patch("answer_agent.httpx.Client", return_value=fake_client),
        patch("answer_agent.time.sleep") as sleep,
    ):
        with pytest.raises(ValidationError):
            AnswerAgent().run("有什么建议？", [evidence])

    assert len(attempts) == 1
    sleep.assert_not_called()
