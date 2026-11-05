import asyncio
import json

import fakeredis.aioredis
from fakeredis import FakeServer
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from api.app import create_app
from models.schemas import PlanningState, UserPreferences
from orchestrator.pipeline import quick_plan
from services.rag import Citation, Embedder, KnowledgeBase, SummaryGenerator, chunk_text
from services.runtime import Runtime, TaskCapacityError
from services.settings import AppSettings
from services.storage import MemoryStore, RedisStore, TERMINAL


REQUEST = {
    "budget": 50000, "departure_city": "北京", "start_date": "2026-12-01",
    "end_date": "2026-12-05", "travel_style": "comfort", "num_travelers": 1,
    "knowledge_question": "文化 美食 预算",
}


def config(**overrides):
    return AppSettings(qdrant_path=":memory:", **overrides)


async def finished(runtime, task_id):
    async with asyncio.timeout(10):
        while True:
            task = await runtime.store.get(task_id)
            if task["status"] in TERMINAL:
                return task
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("overrides", [
    {"budget": -1}, {"num_travelers": 0}, {"num_travelers": 21},
    {"start_date": "2026-12-06"}, {"end_date": "not-a-date"},
    {"end_date": "2027-02-01"},
])
def test_preferences_reject_invalid_constraints(overrides):
    with pytest.raises(ValidationError):
        UserPreferences.model_validate({**REQUEST, **overrides})


async def test_store_event_replay_isolation_ttl_and_empty_arrays():
    stores = [MemoryStore(), RedisStore(client=fakeredis.aioredis.FakeRedis(decode_responses=True))]
    for store in stores:
        await store.create("one", {"status": "queued", "values": []})
        await store.create("two", {"status": "queued"})
        await asyncio.gather(*[
            store.record("one", "progress", {"values": []}, {"values": []}) for _ in range(5)
        ])
        events = await store.events("one", 2)
        assert [event["id"] for event in events] == [3, 4, 5]
        assert events[0]["data"]["values"] == []
        assert (await store.get("one"))["values"] == []
        assert await store.events("two", 0) == []
        await store.cache_set("key", {"values": []}, 10)
        cached = await store.cache_get("key")
        cached["values"].append(1)
        assert await store.cache_get("key") == {"values": []}
        if isinstance(store, RedisStore):
            assert await store.client.ttl(store.keys("one")[0]) > 0
            await store.client.pexpire(store.keys("one")[0], 1)
            await asyncio.sleep(0.02)
            assert await store.get("one") is None
        await store.close()


async def test_qdrant_ingest_replaces_source_filters_city_and_refuses_irrelevance():
    async with httpx.AsyncClient() as http:
        kb = KnowledgeBase(config(demo_seed=False), http)
        await kb.start()
        try:
            await kb.ingest("东京", "guide.md", "文化 博物馆 美食 " * 160)
            await kb.ingest("首尔", "other.md", "首尔独有文化 美食")
            revised = await kb.ingest("东京", "guide.md", "文化 博物馆 步行")
            await kb.ingest("东京", "guide.md", "文化 博物馆 步行")
            count = await kb.client.count(kb.collection, exact=True)
            assert count.count == 2
            hits = await kb.search("东京", "文化 博物馆")
            assert len(hits) == revised["chunks"] == 1
            assert hits[0].source == "guide.md" and hits[0].city == "东京"
            assert await kb.search("东京", "quantumzzz") == []
            assert await kb.search("不存在的城市", "文化") == []
        finally:
            await kb.close()


def test_chunking_overlap_and_bounds():
    assert chunk_text("abcdefgh", size=5, overlap=2) == ["abcde", "defgh", "gh"]
    with pytest.raises(ValueError):
        chunk_text("abc", 5, 5)
    with pytest.raises(ValueError):
        chunk_text(" ")


async def test_langgraph_real_fanout_cache_and_budget_totals():
    runtime = Runtime(config())
    await runtime.start()
    try:
        entered = set()
        gate = asyncio.Event()
        calls = {name: 0 for name in runtime.workflow.agents}
        for name, agent in runtime.workflow.agents.items():
            original = agent.execute

            async def wrapped(state, name=name, original=original):
                calls[name] += 1
                entered.add(name)
                if len(entered) == 3:
                    gate.set()
                await asyncio.wait_for(gate.wait(), 1)
                return await original(state)
            agent.execute = wrapped
        first = await finished(runtime, await runtime.submit(REQUEST))
        second = await finished(runtime, await runtime.submit(REQUEST))
        assert first["status"] == second["status"] == "completed"
        assert all(count == 1 for count in calls.values())
        assert first["result"]["citations"]
        plan = first["result"]["plan"]
        costs = plan["budget_breakdown"]
        assert costs["total_cost"] == pytest.approx(
            costs["flight_cost"] + costs["hotel_cost"] + costs["activity_cost"]
        )
        assert first["result"]["plan"] == second["result"]["plan"]
    finally:
        await runtime.close()


async def test_budget_adjustment_uses_candidates_and_never_researches():
    runtime = Runtime(config())
    await runtime.start()
    try:
        result = await finished(runtime, await runtime.submit({**REQUEST, "budget": 1}))
        assert result["status"] == "infeasible"
        plan = result["result"]["plan"]
        assert plan["adjustment_round"] == 3
        assert plan["budget_breakdown"]["is_within_budget"] is False
        hotel = plan["hotel_result"]
        assert hotel["recommended"] in hotel["hotels"]
        flights = plan["flight_result"]
        assert flights["recommended_outbound"] in flights["outbound_flights"]
        assert flights["recommended_return"] in flights["return_flights"]
        events = await runtime.store.events(result["id"], 0)
        nodes = [event["data"].get("node") for event in events]
        assert nodes.count("flight_result") == 1
        assert nodes.count("hotel_result") == 1
        assert nodes.count("activity_result") == 1
        assert nodes.count("budget") == 4
        original = await quick_plan(budget=1)
        assert original.state == PlanningState.INFEASIBLE
    finally:
        await runtime.close()


async def test_tool_failure_retries_and_does_not_report_false_success():
    runtime = Runtime(config(tool_attempts=2))
    await runtime.start()
    attempts = 0
    async def broken(state):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("provider unavailable")
    runtime.workflow.agents["flight_result"].execute = broken
    try:
        task = await finished(runtime, await runtime.submit(REQUEST))
        assert task["status"] == "failed"
        assert task["error"] == "ConnectError"
        assert attempts == 2
        assert task["result"] is None
    finally:
        await runtime.close()


async def test_task_capacity_cancellation_and_event_stream_disconnect():
    runtime = Runtime(config(max_active_tasks=1))
    await runtime.start()
    entered = asyncio.Event()
    async def slow(state):
        entered.set()
        await asyncio.sleep(60)
    runtime.workflow.agents["flight_result"].execute = slow
    try:
        task_id = await runtime.submit(REQUEST)
        await entered.wait()
        with pytest.raises(TaskCapacityError):
            await runtime.submit(REQUEST)
        stream = runtime.event_stream(task_id)
        assert "queued" in await anext(stream)
        await stream.aclose()
        assert not runtime.tasks[task_id].done()
        runtime.tasks[task_id].cancel()
        result = await finished(runtime, task_id)
        assert result["status"] == "cancelled"
    finally:
        await runtime.close()


async def test_redis_runtime_persists_terminal_result_and_replays_from_second_client():
    server = FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    store = RedisStore(client=client)
    runtime = Runtime(config(), store=store)
    await runtime.start()
    try:
        task = await finished(runtime, await runtime.submit(REQUEST))
        assert task["status"] == "completed"
        other = RedisStore(client=fakeredis.aioredis.FakeRedis(
            server=server, decode_responses=True,
        ))
        loaded = await other.get(task["id"])
        assert loaded["result"] == task["result"]
        chunks = [chunk async for chunk in runtime.event_stream(task["id"], after=2)]
        assert chunks and chunks[0].startswith("id: 3\n")
        assert "event: completed" in chunks[-1]
        await other.close()
    finally:
        await runtime.close()


async def test_llm_repairs_json_and_rejects_fabricated_citations():
    calls = []
    citation = Citation(id="source-1", source="guide.md", city="东京", text="文化体验",
                        vector_score=0.8)
    def provider(request):
        calls.append(json.loads(request.content))
        content = (json.dumps({"summary": "文化体验 [source-1]", "citations": ["source-1"]})
                   if len(calls) > 1 else '{"summary":"错误引用","citations":["invented"]}')
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        generator = SummaryGenerator(config(generation_mode="llm", llm_api_key="test"), http)
        answer = await generator.generate("东京", [citation], {})
        assert len(calls) == 2 and answer.mode == "llm"
        assert answer.citations == ["source-1"]
        await generator.generate("东京", [], {})
        assert len(calls) == 2  # No evidence means no model request.


async def test_embedding_http_orders_vectors_and_checks_dimension():
    def provider(request):
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.0] * 8}, {"index": 0, "embedding": [1.0] * 8},
        ]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        embedder = Embedder(config(embedding_mode="http", embedding_base_url="https://example.test/v1",
                                   embedding_api_key="test", embedding_dimensions=8), http)
        vectors = await embedder.embed(["first", "second"])
        assert vectors[0] == [1.0] * 8
        with pytest.raises(ValueError):
            await embedder.embed(["only-one"])


def test_api_task_sse_replay_auth_and_validation():
    with TestClient(create_app(config(api_key="demo-key"))) as client:
        headers = {"X-API-Key": "demo-key"}
        assert client.post("/api/tasks", json=REQUEST).status_code == 401
        assert client.post("/api/tasks", json={**REQUEST, "budget": 0}, headers=headers).status_code == 422
        response = client.post("/api/tasks", json=REQUEST, headers=headers)
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        with client.stream("GET", f"/api/tasks/{task_id}/events", headers=headers) as stream:
            body = "".join(stream.iter_text())
        assert "event: completed" in body and "event: progress" in body
        response = client.get(f"/api/tasks/{task_id}/events",
                              headers={**headers, "Last-Event-ID": "2"})
        assert response.text.startswith("id: 3\n")
        assert "id: 1\n" not in response.text
        assert client.get(f"/api/tasks/{task_id}/events",
                          headers={**headers, "Last-Event-ID": "-1"}).status_code == 400
        task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        assert task["status"] == "completed" and task["result"]["citations"]
        assert client.get("/api/tasks/missing", headers=headers).status_code == 404
        assert client.get("/api/health").json()["storage"] == "memory"
        assert client.get("/").status_code == 200


def test_documents_endpoint_and_no_results():
    with TestClient(create_app(config(demo_seed=False))) as client:
        document = {"city": "成都", "source": "notes.md", "text": "文化 博物馆 美食"}
        assert client.post("/api/knowledge/documents", json=document).status_code == 200
        hits = client.get("/api/knowledge/search", params={"city": "成都", "question": "文化"})
        assert hits.json()["citations"][0]["source"] == "notes.md"
        unknown = client.post("/api/knowledge/ask", json={"city": "成都", "question": "quantumzzz"})
        assert unknown.json()["answer"]["citations"] == []
        assert client.post("/api/knowledge/documents", json={**document, "text": " "}).status_code == 422
