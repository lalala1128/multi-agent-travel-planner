"""Enhanced FastAPI API. Run from root: uv run uvicorn api.app:app --app-dir python."""
import asyncio
from contextlib import asynccontextmanager
import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from redis.exceptions import RedisError

from models.schemas import UserPreferences
from services.runtime import Runtime, TaskCapacityError
from services.settings import AppSettings, ROOT
from services.storage import TERMINAL


class PlanRequest(UserPreferences):
    knowledge_question: str = Field(default="文化 美食 景点 预算", max_length=1000)
    notes: str = Field(default="", max_length=2000)
    interests: list[str] = Field(default_factory=list, max_length=20)


class DocumentRequest(BaseModel):
    city: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=30000)

    @field_validator("city", "source", "text")
    @classmethod
    def reject_blank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()


class QuestionRequest(BaseModel):
    city: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)


def create_app(settings: AppSettings | None = None, store=None):
    @asynccontextmanager
    async def lifespan(app):
        runtime = Runtime(settings or AppSettings.from_env(), store=store)
        app.state.runtime = runtime
        try:
            await runtime.start()
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Travel Agent · LangGraph + RAG", version="0.2.0", lifespan=lifespan)

    async def authorized(request: Request, x_api_key: Annotated[str | None, Header()] = None):
        expected = request.app.state.runtime.settings.api_key
        if expected and not hmac.compare_digest(x_api_key or "", expected):
            raise HTTPException(401, "Invalid API key")

    protected = [Depends(authorized)]

    async def existing_task(task_id: str):
        task = await app.state.runtime.store.get(task_id)
        if task is None:
            raise HTTPException(404, "Task does not exist or has expired")
        return task

    async def submit(request: PlanRequest):
        try:
            return await app.state.runtime.submit(request.model_dump(mode="json"))
        except TaskCapacityError:
            raise HTTPException(429, "Too many running tasks", headers={"Retry-After": "5"}) from None

    @app.exception_handler(RedisError)
    async def redis_unavailable(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"detail": "Task store is unavailable"})

    @app.get("/", include_in_schema=False)
    async def demo():
        return FileResponse(ROOT / "web" / "index.html")

    @app.get("/api/health")
    async def health():
        runtime = app.state.runtime
        await runtime.store.ping()
        return {
            "status": "ok", "storage": runtime.store.backend, "execution": "in-process",
            "data_mode": "mock", "embedding_mode": runtime.settings.embedding_mode,
            "generation_mode": runtime.settings.generation_mode,
        }

    @app.post("/api/tasks", status_code=202, dependencies=protected)
    async def create_task(request: PlanRequest):
        task_id = await submit(request)
        return {"task_id": task_id, "status_url": f"/api/tasks/{task_id}",
                "events_url": f"/api/tasks/{task_id}/events"}

    @app.get("/api/tasks/{task_id}", dependencies=protected)
    async def get_task(task_id: str):
        return await existing_task(task_id)

    @app.get("/api/tasks/{task_id}/events", dependencies=protected)
    async def task_events(
        task_id: str,
        last_event_id: Annotated[str | None, Header()] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ):
        task = await existing_task(task_id)
        try:
            cursor = int(last_event_id) if last_event_id is not None else after
        except ValueError:
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer") from None
        if cursor < 0:
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer")
        # Reject a future cursor rather than hiding all real events until the task expires.
        history = await app.state.runtime.store.events(task_id, 0)
        if cursor > len(history):
            raise HTTPException(400, "Event cursor is ahead of task history")
        return StreamingResponse(
            app.state.runtime.event_stream(task["id"], cursor), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/plan", dependencies=protected)
    async def create_plan(request: PlanRequest):
        task_id = await submit(request)
        # The worker owns the task; a disconnected HTTP client doesn't cancel execution.
        while True:
            task = await existing_task(task_id)
            if task["status"] in TERMINAL:
                if task["status"] in {"failed", "cancelled"}:
                    raise HTTPException(502, {"task_id": task_id, "error": task["error"]})
                return task
            await asyncio.sleep(0.05)

    @app.post("/api/knowledge/documents", dependencies=protected)
    async def ingest(request: DocumentRequest):
        result = await app.state.runtime.knowledge.ingest(
            request.city, request.source, request.text,
        )
        return result

    @app.get("/api/knowledge/search", dependencies=protected)
    async def search(
        city: Annotated[str, Query(min_length=1, max_length=80)],
        question: Annotated[str, Query(min_length=1, max_length=1000)],
        top_k: Annotated[int, Query(ge=1, le=6)] = 3,
    ):
        hits = await app.state.runtime.knowledge.search(city, question, top_k)
        return {"citations": [hit.model_dump() for hit in hits]}

    @app.post("/api/knowledge/ask", dependencies=protected)
    async def ask(request: QuestionRequest):
        hits = await app.state.runtime.knowledge.search(request.city, request.question)
        answer = await app.state.runtime.generator.generate(request.city, hits, {})
        return {"answer": answer.model_dump(), "sources": [hit.model_dump() for hit in hits]}

    return app


app = create_app()


def start():
    import uvicorn
    uvicorn.run("api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    start()
