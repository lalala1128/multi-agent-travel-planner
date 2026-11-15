import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.exceptions import RedisError

from preference_agent import PreferenceAgent
from qdrant_factory import create_qdrant_client
from rate_limiter import RateLimitExceeded, RateLimiter
from schemas import PlanningState, TaskEvent, TaskRecord, TravelRequest
from settings import load_settings
from task_service import TaskCapacityError, TaskService
from task_store import TaskStore


logger = logging.getLogger(__name__)


def create_app(store=None, planner=None, max_pending: int | None = None):
    settings = load_settings()
    max_pending = settings.task_max_pending if max_pending is None else max_pending

    @asynccontextmanager
    async def lifespan(app):
        service = TaskService(
            store=store if store is not None else TaskStore(),
            planner=planner,
            max_pending=max_pending,
        )
        app.state.task_service = service
        app.state.rate_limiter = RateLimiter(
            client=service.store.client,
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="旅游规划 Agent 学习版", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Last-Event-ID", "X-API-Key"],
        )
    preference_agent = PreferenceAgent()

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "access method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.exception_handler(RedisError)
    async def redis_unavailable(request, error):
        return JSONResponse(status_code=503, content={"detail": "任务存储暂不可用"})

    def submit(request):
        try:
            return app.state.task_service.submit(request)
        except TaskCapacityError:
            raise HTTPException(429, "任务已满，请稍后提交", headers={"Retry-After": "5"}) from None

    def require_api_key(
        x_api_key: Annotated[str | None, Header()] = None,
    ):
        if settings.api_key and not secrets.compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(401, "缺少或无效的 X-API-Key")

    def enforce_rate_limit(request: Request):
        api_key = request.headers.get("X-API-Key")
        subject = api_key or (request.client.host if request.client else "unknown")
        try:
            app.state.rate_limiter.check(subject)
        except RateLimitExceeded as error:
            raise HTTPException(
                429,
                "请求过于频繁，请稍后重试",
                headers={"Retry-After": str(error.retry_after)},
            ) from None

    def format_sse(event: TaskEvent) -> str:
        """将一个已持久化事件编码为 Server-Sent Events 文本。"""
        data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        return f"id: {event.id}\nevent: {event.event}\ndata: {data}\n\n"

    @app.get("/healthz")
    def healthz():
        dependencies = {}
        try:
            app.state.task_service.store.client.ping()
            dependencies["redis"] = "ok"
        except RedisError:
            dependencies["redis"] = "unavailable"

        client = create_qdrant_client(Path(__file__).resolve().parent)
        try:
            client.get_collections()
            dependencies["qdrant"] = "ok"
        except Exception:
            dependencies["qdrant"] = "unavailable"
        finally:
            client.close()

        if all(value == "ok" for value in dependencies.values()):
            return {"status": "ok", "dependencies": dependencies}
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "dependencies": dependencies},
        )

    @app.get("/health")
    def health():
        return healthz()

    protected = [Depends(require_api_key), Depends(enforce_rate_limit)]

    @app.post("/preferences", dependencies=protected)
    def collect_preferences(request: TravelRequest):
        result = preference_agent.run(request)
        return {"message": "旅行偏好处理完成", "preferences": result.model_dump()}

    @app.post("/recommendations", response_model=PlanningState, dependencies=protected)
    def recommend_destination(request: TravelRequest):
        # 同步入口也走同一个执行器，避免绕过任务容量和单线程限制。
        task_id, future = submit(request)
        return future.result()

    @app.post("/tasks", status_code=202, dependencies=protected)
    def create_task(request: TravelRequest):
        task_id, future = submit(request)
        return {
            "task_id": task_id,
            "status_url": f"/tasks/{task_id}",
            "events_url": f"/tasks/{task_id}/events",
        }

    @app.get("/tasks/{task_id}", response_model=TaskRecord, dependencies=protected)
    def get_task(task_id: UUID):
        record = app.state.task_service.store.get(str(task_id))
        if record is None:
            raise HTTPException(404, "任务不存在或已过期")
        return record

    @app.get("/tasks/{task_id}/events", dependencies=protected)
    async def stream_task_events(
        task_id: UUID,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        """推送任务事件；客户端重连时由 Last-Event-ID 补发遗漏事件。"""
        if last_event_id is None:
            after_id = 0
        else:
            try:
                after_id = int(last_event_id)
            except ValueError as error:
                raise HTTPException(422, "Last-Event-ID 必须是非负整数") from error
            if after_id < 0:
                raise HTTPException(422, "Last-Event-ID 必须是非负整数")

        store = app.state.task_service.store
        task_id_text = str(task_id)
        record = await asyncio.to_thread(store.get, task_id_text)
        if record is None:
            raise HTTPException(404, "任务不存在或已过期")

        async def event_stream():
            nonlocal after_id
            while True:
                try:
                    events = await asyncio.to_thread(
                        store.list_events, task_id_text, after_id,
                    )
                    for event in events:
                        after_id = event.id
                        yield format_sse(event)

                    record = await asyncio.to_thread(store.get, task_id_text)
                except RedisError:
                    yield "event: storage_error\ndata: {\"detail\": \"任务存储暂不可用\"}\n\n"
                    return

                if record is None:
                    yield "event: expired\ndata: {\"detail\": \"任务已过期\"}\n\n"
                    return
                if record.status in {"succeeded", "failed"}:
                    return

                # 注释行是 SSE 心跳，不会触发浏览器的 message 回调。
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
