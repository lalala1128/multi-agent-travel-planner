import fakeredis

from metrics import Metrics
from schemas import PlanningState, TravelRequest
from task_service import TaskService
from task_store import TaskStore


class CompletedPlanner:
    def run(self, request: TravelRequest) -> PlanningState:
        return PlanningState(preferences=request, status="completed")


def test_task_service_records_final_task_metric():
    store = TaskStore(client=fakeredis.FakeRedis(decode_responses=True))
    metrics = Metrics()
    service = TaskService(store, planner=CompletedPlanner(), metrics=metrics)
    try:
        _, future = service.submit(TravelRequest(departure_city="北京", budget=3500, days=5))
        future.result(timeout=3)
        output = metrics.render_prometheus()
        assert 'travel_agent_tasks_total{outcome="succeeded",final_stage="completed"} 1' in output
    finally:
        service.close()
