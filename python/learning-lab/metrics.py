"""轻量 Prometheus 指标，不引入额外的运行时依赖。"""

from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._requests = Counter()
        self._duration_seconds = Counter()

    def observe_request(self, method: str, path: str, status: int, duration_seconds: float):
        key = (method, path, str(status))
        with self._lock:
            self._requests[key] += 1
            self._duration_seconds[key] += duration_seconds

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
        return "\n".join(lines) + "\n"
