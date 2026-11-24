from threading import Event
import time
from unittest.mock import Mock
from uuid import uuid4

import fakeredis
from fastapi.testclient import TestClient
import httpx
import pytest
from redis.exceptions import ConnectionError

from main import create_app
from schemas import PlanningState, TravelRequest
from task_service import TaskService
from task_store import TaskStore


REQUEST = {"departure_city": "北京", "budget": 3500, "days": 5}


def make_store():
    return TaskStore(client=fakeredis.FakeRedis(decode_responses=True))


def wait_for_task(client, task_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        record = response.json()
        if record["status"] in {"succeeded", "failed"}:
            return record
        time.sleep(0.01)
    pytest.fail("任务没有在测试时限内结束")


def test_task_store_preserves_data_and_ttl():
    store = make_store()
    try:
        record = store.create(TravelRequest(**REQUEST))
        loaded = store.get(record.id)
        assert loaded.status == "queued"
        assert loaded.request.interests == []
        assert loaded.result is None
        assert 0 < store.client.ttl(store.key(record.id)) <= 86400
        assert store.get(str(uuid4())) is None
    finally:
        store.close()


def test_submission_returns_before_execution_and_rejects_excess_tasks():
    entered = Event()
    release = Event()

    class SlowPlanner:
        def run(self, request):
            entered.set()
            assert release.wait(3)
            return PlanningState(preferences=request, status="completed")

    with TestClient(create_app(make_store(), SlowPlanner(), max_pending=1)) as client:
        try:
            response = client.post("/tasks", json=REQUEST)
            assert response.status_code == 202
            task_id = response.json()["task_id"]
            assert entered.wait(2)
            assert client.get(f"/tasks/{task_id}").json()["status"] == "running"
            waiting = client.get(response.json()["report_url"])
            assert waiting.status_code == 200
            assert "正在规划" in waiting.text and 'http-equiv="refresh"' in waiting.text
            assert client.post("/tasks", json=REQUEST).status_code == 429
        finally:
            release.set()
        assert wait_for_task(client, task_id)["status"] == "succeeded"


def test_over_budget_result_is_a_successfully_executed_task():
    class Planner:
        def run(self, request):
            return PlanningState(preferences=request, status="over_budget", adjustment_count=2)

    with TestClient(create_app(make_store(), Planner())) as client:
        response = client.post("/tasks", json=REQUEST)
        task = wait_for_task(client, response.json()["task_id"])
        assert task["status"] == "succeeded"
        assert task["result"]["status"] == "over_budget"
        assert task["error"] is None
        report = client.get(response.json()["report_url"])
        assert report.status_code == 200 and "text/html" in report.headers["content-type"]
        assert "北京" in report.text and 'http-equiv="refresh"' not in report.text
        assert client.get(f"/tasks/{uuid4()}/report").status_code == 404
        assert client.get(f"/tasks/{uuid4()}").status_code == 404
        assert client.post("/tasks", json={**REQUEST, "budget": -1}).status_code == 422


def test_failure_records_only_error_type():
    class BrokenPlanner:
        def run(self, request):
            raise httpx.ConnectError("private-provider-detail")

    with TestClient(create_app(make_store(), BrokenPlanner())) as client:
        response = client.post("/tasks", json=REQUEST)
        task = wait_for_task(client, response.json()["task_id"])
        assert task["status"] == "failed"
        assert task["result"] is None
        assert task["error"] == "ConnectError"
        assert task["error_stage"] == "workflow_execution"
        assert task["error_location"].startswith("task_service.py:")
        assert "private-provider-detail" not in str(task)
        report = client.get(response.json()["report_url"])
        assert "规划失败" in report.text and "private-provider-detail" not in report.text


@pytest.mark.parametrize("filename,expected_stage", [
    ("answer_agent.py", "answer_generation"),
    ("knowledge_agent.py", "knowledge_retrieval"),
])
def test_failure_identifies_project_stage_without_leaking_details(filename, expected_stage):
    namespace = {"ConnectError": httpx.ConnectError}
    exec(compile(
        "def run(self, request):\n    raise ConnectError('private-provider-detail')\n",
        filename, "exec",
    ), namespace)
    planner = type("BrokenPlanner", (), {"run": namespace["run"]})()
    with TestClient(create_app(make_store(), planner)) as client:
        task_id = client.post("/tasks", json=REQUEST).json()["task_id"]
        task = wait_for_task(client, task_id)
        assert task["error_stage"] == expected_stage
        assert task["error_location"] == f"{filename}:2"
        assert "private-provider-detail" not in str(task)


def test_tasks_are_executed_serially_and_results_are_isolated():
    entered = Event()
    release = Event()
    budgets = []

    class SerialPlanner:
        def run(self, request):
            budgets.append(request.budget)
            if len(budgets) == 1:
                entered.set()
                assert release.wait(3)
            return PlanningState(preferences=request, status="completed")

    store = make_store()
    service = TaskService(store, SerialPlanner())
    try:
        first_id, first = service.submit(TravelRequest(**REQUEST))
        assert entered.wait(2)
        second_id, second = service.submit(TravelRequest(**{**REQUEST, "budget": 2500}))
        assert store.get(second_id).status == "queued"
        assert budgets == [3500]
        release.set()
        first.result(timeout=3)
        second.result(timeout=3)
        assert budgets == [3500, 2500]
        assert store.get(first_id).result.preferences.budget == 3500
        assert store.get(second_id).result.preferences.budget == 2500
    finally:
        release.set()
        service.close()


def test_expired_records_are_not_recreated_by_updates():
    store = make_store()
    try:
        record = store.create(TravelRequest(**REQUEST))
        store.client.delete(store.key(record.id))
        with pytest.raises(LookupError):
            store.save_with_event(record, event="running")
        assert store.get(record.id) is None
    finally:
        store.close()


def test_redis_failure_prevents_submission():
    backend = Mock()
    backend.scan_iter.return_value = iter(())
    backend.incr.side_effect = ConnectionError("模拟 Redis 故障")
    # 创建任务已改为通过 Lua EVAL 原子写入快照与首个事件。
    backend.eval.side_effect = ConnectionError("模拟 Redis 故障")
    planner = Mock()
    with TestClient(create_app(TaskStore(client=backend), planner)) as client:
        response = client.post("/tasks", json=REQUEST)
        assert response.status_code == 503
        planner.run.assert_not_called()


def test_existing_sync_endpoint_still_returns_planning_state():
    class Planner:
        def run(self, request):
            return PlanningState(preferences=request, status="completed")

    with TestClient(create_app(make_store(), Planner())) as client:
        response = client.post("/recommendations", json=REQUEST)
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["preferences"]["budget"] == 3500


def test_sse_replays_events_and_honors_last_event_id():
    class Planner:
        def run(self, request):
            return PlanningState(preferences=request, status="completed")

    with TestClient(create_app(make_store(), Planner())) as client:
        created = client.post("/tasks", json=REQUEST).json()
        task_id = created["task_id"]
        wait_for_task(client, task_id)

        response = client.get(created["events_url"])
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "id: 1\nevent: queued" in response.text
        assert "id: 2\nevent: running" in response.text
        assert "id: 3\nevent: succeeded" in response.text

        replay = client.get(
            created["events_url"],
            headers={"Last-Event-ID": "1"},
        )
        assert "id: 1\nevent: queued" not in replay.text
        assert "id: 2\nevent: running" in replay.text
        assert "id: 3\nevent: succeeded" in replay.text


def test_sse_rejects_invalid_last_event_id():
    class Planner:
        def run(self, request):
            return PlanningState(preferences=request, status="completed")

    with TestClient(create_app(make_store(), Planner())) as client:
        task_id = client.post("/tasks", json=REQUEST).json()["task_id"]
        response = client.get(
            f"/tasks/{task_id}/events",
            headers={"Last-Event-ID": "not-a-number"},
        )
        assert response.status_code == 422


def test_progress_capable_planner_persists_node_events():
    class ProgressPlanner:
        def run_with_progress(self, request, on_node_complete, on_node_retry):
            on_node_complete("preferences")
            on_node_complete("destination")
            on_node_complete("budget")
            return PlanningState(preferences=request, status="completed")

    store = make_store()
    service = TaskService(store, ProgressPlanner())
    try:
        task_id, future = service.submit(TravelRequest(**REQUEST))
        future.result(timeout=3)
        events = store.list_events(task_id)

        assert [event.event for event in events] == [
            "queued", "running", "progress", "progress", "progress", "succeeded",
        ]
        assert [event.data["node"] for event in events if event.event == "progress"] == [
            "preferences", "destination", "budget",
        ]
        assert events[2].data["message"] == "偏好收集完成"
    finally:
        service.close()


def test_retry_progress_event_is_persisted_without_error_detail():
    class RetryPlanner:
        def run_with_progress(self, request, on_node_complete, on_node_retry):
            on_node_retry("answer", 2, httpx.ConnectError("provider detail"))
            on_node_complete("answer")
            return PlanningState(preferences=request, status="completed")

    store = make_store()
    service = TaskService(store, RetryPlanner())
    try:
        task_id, future = service.submit(TravelRequest(**REQUEST))
        future.result(timeout=3)
        retry_event = next(
            event for event in store.list_events(task_id)
            if event.data.get("phase") == "retry"
        )

        assert retry_event.event == "progress"
        assert retry_event.data["node"] == "answer"
        assert retry_event.data["attempt"] == 2
        assert retry_event.data["error_type"] == "ConnectError"
        assert "provider detail" not in str(retry_event.data)
    finally:
        service.close()


def test_startup_marks_unfinished_records_as_interrupted():
    store = make_store()
    record = store.create(TravelRequest(**REQUEST))
    record.status = "running"
    store.save_with_event(record, event="running")

    service = TaskService(store, planner=Mock())
    try:
        recovered = store.get(record.id)
        events = store.list_events(record.id)
        assert recovered.status == "failed"
        assert recovered.error == "ServiceRestarted"
        assert recovered.error_stage == "task_recovery"
        assert events[-1].event == "failed"
        assert events[-1].data["stage"] == "task_recovery"
    finally:
        service.close()
