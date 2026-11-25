import asyncio
import json
import logging
import secrets
import re
from html import escape
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from redis.exceptions import RedisError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from metrics import Metrics
from itinerary_report import render_report
from online_plan import OnlineRequest, OnlinePlanError, generate_online_plan
from preference_agent import PreferenceAgent
from hotelbeds_client import (
    HotelbedsClient,
    HotelbedsConfigurationError,
    HotelbedsResponseError,
    HotelbedsUpstreamError,
)
from qdrant_factory import create_qdrant_client
from rate_limiter import RateLimitExceeded, RateLimiter
from schemas import HotelSearchRequest, HotelSearchResponse, PlanningState, TaskEvent, TaskRecord, TravelRequest
from settings import load_settings
from task_service import TaskCapacityError, TaskService
from task_store import TaskStore


logger = logging.getLogger(__name__)


def create_app(store=None, planner=None, max_pending: int | None = None):
    settings = load_settings()
    max_pending = settings.task_max_pending if max_pending is None else max_pending

    @asynccontextmanager
    async def lifespan(app):
        metrics = Metrics()
        service = TaskService(
            store=store if store is not None else TaskStore(),
            planner=planner,
            max_pending=max_pending,
            metrics=metrics,
        )
        app.state.task_service = service
        app.state.metrics = metrics
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
    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    preference_agent = PreferenceAgent()

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if settings.trip_edge_token:
            response.headers["Cache-Control"] = "private, no-store"
        duration_seconds = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        app.state.metrics.observe_request(
            request.method,
            path,
            response.status_code,
            duration_seconds,
        )
        logger.info(
            "access method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            path,
            response.status_code,
            duration_seconds * 1000,
        )
        return response

    @app.exception_handler(RedisError)
    async def redis_unavailable(request, error):
        return JSONResponse(status_code=503, content={"detail": "任务存储暂不可用"})

    def submit(request, owner=None):
        try:
            return app.state.task_service.submit(request, owner=owner)
        except TaskCapacityError:
            raise HTTPException(429, "任务已满，请稍后提交", headers={"Retry-After": "5"}) from None

    def trip_owner(request: Request) -> str | None:
        owner = request.headers.get("x-trip-user")
        token = settings.trip_edge_token
        if owner is None and not token:
            return None
        provided = request.headers.get("x-trip-edge-token", "")
        if (not token or len(token) < 32 or not owner
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", owner)
                or not secrets.compare_digest(provided.encode(), token.encode())):
            raise HTTPException(401, "请通过 HTTPS 入口登录")
        return owner

    def require_api_key(
        owner: Annotated[str | None, Depends(trip_owner)],
        x_api_key: Annotated[str | None, Header()] = None,
    ):
        if not owner and settings.api_key and not secrets.compare_digest((x_api_key or "").encode(), settings.api_key.encode()):
            raise HTTPException(401, "缺少或无效的 X-API-Key")

    def enforce_rate_limit(request: Request, owner: str | None = Depends(trip_owner)):
        api_key = request.headers.get("X-API-Key")
        subject = owner or api_key or (request.client.host if request.client else "unknown")
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

    @app.get("/livez")
    def livez():
        """仅验证 API 进程存活；部署编排器不应以外部依赖状态重启它。"""
        return {"status": "ok"}

    @app.get("/metrics", dependencies=[Depends(require_api_key)])
    def metrics():
        return PlainTextResponse(
            app.state.metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    protected = [Depends(require_api_key), Depends(enforce_rate_limit)]

    mobile_slots = asyncio.Semaphore(2)

    @app.get("/mobile", response_class=HTMLResponse, include_in_schema=False)
    def mobile_form(owner: str | None = Depends(trip_owner)):
        page = Path(__file__).with_name("mobile_plan.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace("{{key_visibility}}", "" if settings.api_key and not owner else "hidden"))

    @app.post("/mobile/plan", dependencies=protected)
    async def mobile_plan(req: OnlineRequest):
        if mobile_slots.locked():
            raise HTTPException(429, "正在为其他旅客规划，请稍后再试。")
        async with mobile_slots:
            try:
                return await asyncio.wait_for(generate_online_plan(req), timeout=90)
            except OnlinePlanError as error:
                raise HTTPException(502, str(error)) from None
            except TimeoutError:
                raise HTTPException(504, "规划超时，请稍后重试。") from None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def trip_form(owner: str | None = Depends(trip_owner)):
        page = Path(__file__).with_name("trip_form.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace("{{key_visibility}}", "" if settings.api_key and not owner else "hidden")
                            .replace("{{library_link}}", '<a href="/my/trips">我的行程</a>' if owner else ""))

    @app.get("/my/trips", response_class=HTMLResponse, dependencies=protected)
    def my_trips(owner: str | None = Depends(trip_owner), page: int = Query(1, ge=1, le=1000000)):
        if not owner:
            raise HTTPException(401, "请使用个人账户登录")
        records = app.state.task_service.store.saved_trips(owner, (page - 1) * 20, 21)
        items = []
        for record in records[:20]:
            destination = record.result.destination if record.result else None
            city = destination.city if destination else record.request.destination_city or "旅行计划"
            items.append(f'<li><a href="/tasks/{escape(record.id)}/report">{escape(city)} · '
                         f'{record.request.days} 天</a> · {record.created_at.date()}</li>')
        prev = f'<a href="?page={page-1}">上一页</a>' if page > 1 else ""
        more = f'<a href="?page={page+1}">下一页</a>' if len(records) > 20 else ""
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                            '<meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<title>我的行程</title><main style="max-width:44rem;margin:auto;padding:1rem;line-height:2">'
                            f'<h1>我的行程</h1><p>{escape(owner)}</p><a href="/">新建旅行预算</a>'
                            + ('<ul>' + ''.join(items) + '</ul>' if items else '<p>本页暂无已完成行程。</p>')
                            + f'{prev} {more}</main></html>', headers={"Cache-Control": "private, no-store"})

    @app.post(
        "/providers/hotelbeds/hotel-offers",
        response_model=HotelSearchResponse,
        dependencies=protected,
    )
    async def search_hotelbeds_offers(request: HotelSearchRequest):
        """查询 Hotelbeds 酒店可用性；只读，不发起核价或预订。"""
        try:
            return await asyncio.to_thread(HotelbedsClient().search, request)
        except HotelbedsConfigurationError as exc:
            # 只返回配置项名称或文件状态，不返回任何密钥、密码或证书内容。
            raise HTTPException(503, f"Hotelbeds 配置不可用：{exc}") from None
        except (HotelbedsUpstreamError, HotelbedsResponseError):
            raise HTTPException(502, "Hotelbeds 酒店报价暂不可用") from None

    @app.post("/preferences", dependencies=protected)
    def collect_preferences(request: TravelRequest):
        result = preference_agent.run(request)
        return {"message": "旅行偏好处理完成", "preferences": result.model_dump()}

    @app.post("/recommendations", response_model=PlanningState, dependencies=protected)
    def recommend_destination(request: TravelRequest, owner: str | None = Depends(trip_owner)):
        # 同步入口也走同一个执行器，避免绕过任务容量和单线程限制。
        task_id, future = submit(request, owner)
        return future.result()

    @app.post("/tasks", status_code=202, dependencies=protected)
    def create_task(request: TravelRequest, owner: str | None = Depends(trip_owner)):
        task_id, future = submit(request, owner)
        return {
            "task_id": task_id,
            "status_url": f"/tasks/{task_id}",
            "report_url": f"/tasks/{task_id}/report",
            "events_url": f"/tasks/{task_id}/events",
        }

    @app.get("/tasks/{task_id}", response_model=TaskRecord, dependencies=protected)
    def get_task(task_id: UUID, owner: str | None = Depends(trip_owner)):
        record = app.state.task_service.store.get(str(task_id))
        if record is None or record.owner != owner:
            raise HTTPException(404, "任务不存在或已过期")
        return record

    @app.get("/tasks/{task_id}/report", response_class=HTMLResponse, dependencies=protected)
    def task_report(task_id: UUID, owner: str | None = Depends(trip_owner)):
        return HTMLResponse(render_report(get_task(task_id, owner)), headers={"Cache-Control": "no-store"})

    @app.get("/tasks/{task_id}/events", dependencies=protected)
    async def stream_task_events(
        task_id: UUID,
        owner: str | None = Depends(trip_owner),
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
        if record is None or record.owner != owner:
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
