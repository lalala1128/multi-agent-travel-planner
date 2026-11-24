"""Redis 保存记录，单工作线程在 API 进程内执行规划。"""

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
from threading import BoundedSemaphore
import time
import traceback

from schemas import TaskRecord, TravelRequest
from task_store import TaskStore


logger = logging.getLogger(__name__)


NODE_MESSAGES = {
    "preferences": "偏好收集完成",
    "destination": "目的地推荐完成",
    "flight": "航班检索完成",
    "hotel": "酒店检索完成",
    "activity": "活动规划完成",
    "knowledge": "知识库检索完成",
    "budget": "预算校验完成",
    "adjust": "预算调整完成",
    "completed": "规划结果满足预算",
    "over_budget": "预算约束不可行",
    "budget_unverified": "酒店报价或参考汇率不可用，暂无法核算总价",
    "answer": "资料摘要完成",
}


class TaskCapacityError(Exception):
    pass


def locate_failure(error: Exception, default_stage: str):
    """仅返回允许展示的阶段和项目文件位置，不包含异常原文或凭据。"""
    frames = traceback.extract_tb(error.__traceback__)
    embedding_frame = any("fastembed" in Path(frame.filename).parts for frame in frames)
    stages = {
        "hotelbeds_client.py": "hotel_availability",
        "answer_agent.py": "answer_generation",
        "knowledge_agent.py": "embedding" if embedding_frame else "knowledge_retrieval",
        "knowledge_cache.py": "knowledge_cache",
        "task_store.py": "task_storage",
        "travel_graph.py": "workflow_execution",
        "pipeline.py": "workflow_execution",
        "task_service.py": default_stage,
    }
    for frame in reversed(frames):
        name = Path(frame.filename).name
        if name in stages:
            return stages[name], f"{name}:{frame.lineno}"
    return default_stage, None


class TaskService:
    def __init__(self, store: TaskStore, planner=None, max_pending: int = 8, metrics=None):
        if max_pending < 1:
            raise ValueError("任务容量必须大于零")
        self.store = store
        self.planner = planner
        self.metrics = metrics
        # 同时只运行一个规划任务，避免打开同一个本地 Qdrant 目录。
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="travel-task")
        self.slots = BoundedSemaphore(max_pending)
        self.closed = False
        self.recover_interrupted_tasks()

    def recover_interrupted_tasks(self):
        """启动时终止旧进程遗留任务，避免重复调用外部模型。"""
        for record in self.store.list_unfinished():
            record.status = "failed"
            record.result = None
            record.error = "ServiceRestarted"
            record.error_stage = "task_recovery"
            record.error_location = None
            self.store.save_with_event(
                record,
                event="failed",
                data={
                    "message": "服务重启，未完成任务已终止，请重新提交",
                    "error": record.error,
                    "stage": record.error_stage,
                },
            )

    def submit(self, request: TravelRequest):
        if self.closed:
            raise RuntimeError("任务执行器已关闭")
        if not self.slots.acquire(blocking=False):
            raise TaskCapacityError("运行和排队的任务已达到上限")
        try:
            record = self.store.create(request)
            future = self.executor.submit(self._execute, record)
        except Exception:
            self.slots.release()
            raise
        future.add_done_callback(lambda completed: self.slots.release())
        return record.id, future

    def _execute(self, record: TaskRecord):
        started = time.perf_counter()
        stage = "task_storage"
        try:
            record.status = "running"
            self.store.save_with_event(
                record,
                event="running",
                data={"message": "任务开始执行"},
            )

            if self.planner is None:
                stage = "loading_workflow"
                # 首次请求才在工作线程内加载模型和图。
                from pipeline import TravelPlanningPipeline
                self.planner = TravelPlanningPipeline()

            stage = "workflow_execution"
            def report_node_complete(node_name: str):
                self.store.append_event(
                    record.id,
                    event="progress",
                    data={
                        "node": node_name,
                        "message": NODE_MESSAGES.get(node_name, f"{node_name} 节点完成"),
                    },
                )

            def report_node_retry(node_name: str, attempt: int, error: Exception):
                self.store.append_event(
                    record.id,
                    event="progress",
                    data={
                        "node": node_name,
                        "phase": "retry",
                        "attempt": attempt,
                        "error_type": type(error).__name__,
                        "message": f"{node_name} 节点网络异常，准备第 {attempt} 次尝试",
                    },
                )

            run_with_progress = getattr(self.planner, "run_with_progress", None)
            if callable(run_with_progress):
                result = run_with_progress(
                    record.request,
                    report_node_complete,
                    report_node_retry,
                )
            else:
                # 注入的测试/替代规划器只需实现 run()，无需强制支持进度回调。
                result = self.planner.run(record.request)
            record.result = result
            record.status = "succeeded"
            self.store.save_with_event(
                record,
                event="succeeded",
                data={
                    "message": "规划完成",
                    "plan_status": result.status,
                },
            )
            if self.metrics is not None:
                self.metrics.observe_task(
                    outcome="succeeded",
                    final_stage=result.status,
                    duration_seconds=time.perf_counter() - started,
                )
            return result
        except Exception as error:
            record.status = "failed"
            record.result = None
            # 不把供应商响应、URL 或凭据写进错误字段。
            record.error = type(error).__name__
            record.error_stage, record.error_location = locate_failure(error, stage)
            try:
                self.store.save_with_event(
                    record,
                    event="failed",
                    data={
                        "message": "任务执行失败",
                        "error": record.error,
                        "stage": record.error_stage,
                    },
                )
            except Exception:
                logger.error("任务 %s 的失败状态无法写入 Redis", record.id)
            logger.error(
                "任务 %s 执行失败：%s，阶段=%s，位置=%s",
                record.id, type(error).__name__, record.error_stage, record.error_location,
            )
            if self.metrics is not None:
                self.metrics.observe_task(
                    outcome="failed",
                    final_stage=record.error_stage or stage,
                    duration_seconds=time.perf_counter() - started,
                )
            raise

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=True)
        self.store.close()
