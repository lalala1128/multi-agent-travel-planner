"""轻量 Prometheus 指标，不引入额外的运行时依赖。"""

from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._requests = Counter()
        self._duration_seconds = Counter()
        self._tasks = Counter()
        self._task_duration_seconds = Counter()

    def observe_request(self, method: str, path: str, status: int, duration_seconds: float):
        key = (method, path, str(status))
        with self._lock:
            self._requests[key] += 1
            self._duration_seconds[key] += duration_seconds

    def observe_task(self, outcome: str, final_stage: str, duration_seconds: float):
        """记录任务最终结果；标签只使用固定状态，避免任务 ID 造成高基数。"""
        key = (outcome, final_stage)
        with self._lock:
            self._tasks[key] += 1
            self._task_duration_seconds[key] += duration_seconds

    def render_prometheus(self) -> str:
        lines = [
            "# HELP travel_agent_http_requests_total Completed HTTP requests.",
            "# TYPE travel_agent_http_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), value in sorted(self._requests.items()):
                labels = f'method="{method}",path="{path}",status="{status}"'
                lines.append(f"travel_agent_http_requests_total{{{labels}}} {value}")
            lines.extend([
                "# HELP travel_agent_http_request_duration_seconds_total Total request duration in seconds.",
                "# TYPE travel_agent_http_request_duration_seconds_total counter",
            ])
            for (method, path, status), value in sorted(self._duration_seconds.items()):
                labels = f'method="{method}",path="{path}",status="{status}"'
                lines.append(f"travel_agent_http_request_duration_seconds_total{{{labels}}} {value:.6f}")
            lines.extend([
                "# HELP travel_agent_tasks_total Completed planning tasks.",
                "# TYPE travel_agent_tasks_total counter",
            ])
            for (outcome, stage), value in sorted(self._tasks.items()):
                labels = f'outcome="{outcome}",final_stage="{stage}"'
                lines.append(f"travel_agent_tasks_total{{{labels}}} {value}")
            lines.extend([
                "# HELP travel_agent_task_duration_seconds_total Total planning task duration in seconds.",
                "# TYPE travel_agent_task_duration_seconds_total counter",
            ])
            for (outcome, stage), value in sorted(self._task_duration_seconds.items()):
                labels = f'outcome="{outcome}",final_stage="{stage}"'
                lines.append(f"travel_agent_task_duration_seconds_total{{{labels}}} {value:.6f}")
        return "\n".join(lines) + "\n"
