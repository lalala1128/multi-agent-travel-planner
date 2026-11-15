from metrics import Metrics


def test_metrics_render_uses_route_template_labels():
    metrics = Metrics()
    metrics.observe_request("GET", "/tasks/{task_id}", 200, 0.125)
    output = metrics.render_prometheus()
    assert 'path="/tasks/{task_id}"' in output
    assert "travel_agent_http_requests_total" in output


def test_metrics_include_task_outcome_and_duration():
    metrics = Metrics()
    metrics.observe_task("succeeded", "completed", 1.25)
    output = metrics.render_prometheus()
    assert 'outcome="succeeded",final_stage="completed"' in output
    assert "travel_agent_task_duration_seconds_total" in output
