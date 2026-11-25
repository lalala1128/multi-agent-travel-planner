import asyncio
from types import SimpleNamespace

import httpx
import pytest

import online_plan
from online_plan import OnlinePlanError, OnlineRequest, generate_online_plan


@pytest.mark.parametrize("mode", ["valid", "unavailable", "invalid_citation"])
def test_search_before_generation(monkeypatch, mode):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            if mode == "unavailable":
                return httpx.Response(503)
            page = {"title":"厦门", "pageid":15, "extract":"鼓浪屿可安排步行游览。"}
            return httpx.Response(200, json={"query":{"pages":{"15":page}}})
        assert len([r for r in calls if r.method == "GET"]) == 2
        content = '{"days":[{"morning":"散步","afternoon":"午休","evening":"休息","sources":[1]}],"budget_note":"估算","verify_before_departure":"查天气"}'
        if mode == "invalid_citation":
            content = content.replace("[1]", "[88]")
        return httpx.Response(200,json={"choices":[{"message":{"content":content}}]})

    client_cls = httpx.AsyncClient
    monkeypatch.setattr(online_plan.httpx,"AsyncClient",lambda **kw:client_cls(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(online_plan,"AnswerAgent",lambda:SimpleNamespace(
        api_key="unit-test",base_url="https://model.test",model="test"))
    req = OnlineRequest(city="厦门", days=1, needs="想散步")
    if mode == "valid":
        result = asyncio.run(generate_online_plan(req))
        assert result["plan"]["days"][0]["sources"] == [1]
        assert result["sources"][0]["url"] == "https://zh.wikivoyage.org/?curid=15"
    else:
        with pytest.raises(OnlinePlanError):
            asyncio.run(generate_online_plan(req))
        assert sum(r.method=="POST" for r in calls) == (2 if mode=="invalid_citation" else 0)
