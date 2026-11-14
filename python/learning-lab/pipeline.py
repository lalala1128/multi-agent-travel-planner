from schemas import TravelRequest, PlanningState
from travel_graph import build_graph


class TravelPlanningPipeline:
    def run(self, request: TravelRequest) -> PlanningState:
        return self._run(request)

    def run_with_progress(
        self,
        request: TravelRequest,
        on_node_complete,
        on_node_retry=None,
    ) -> PlanningState:
        """执行规划，并上报节点完成与可恢复网络重试。"""
        return self._run(
            request,
            on_node_complete=on_node_complete,
            on_node_retry=on_node_retry,
        )

    @staticmethod
    def _run(
        request: TravelRequest,
        on_node_complete=None,
        on_node_retry=None,
    ) -> PlanningState:
        initial_state = PlanningState(
            preferences=request,
        )

        # 图很轻量，按任务创建可避免进度回调串到其他任务。
        graph = build_graph(
            on_node_complete=on_node_complete,
            on_node_retry=on_node_retry,
        )
        output = graph.invoke(initial_state)

        return PlanningState.model_validate(output)
