import asyncio
import contextlib
from datetime import datetime, timezone
import json
from uuid import uuid4

import httpx
from loguru import logger

from orchestrator.graph import TravelGraph
from services.rag import KnowledgeBase, SummaryGenerator
from services.settings import AppSettings, ROOT
from services.storage import MemoryStore, RedisStore, TERMINAL


class TaskCapacityError(Exception):
    pass


class Runtime:
    """One API worker owns execution. Disconnecting SSE never cancels the task."""

    def __init__(self, settings: AppSettings, store=None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=30)
        self.store = store if store is not None else (
            RedisStore(settings.redis_url, settings.task_ttl) if settings.redis_url
            else MemoryStore(settings.task_ttl)
        )
        self.knowledge = KnowledgeBase(settings, self.http)
        self.generator = SummaryGenerator(settings, self.http)
        self.workflow = TravelGraph(settings, self.store, self.knowledge, self.generator)
        self.tasks: dict[str, asyncio.Task] = {}
        self._submission_lock = asyncio.Lock()

    async def start(self):
        await self.store.ping()
        await self.knowledge.start()
        if self.settings.demo_seed:
            for path in sorted((ROOT / "knowledge").glob("*.md")):
                await self.knowledge.ingest(path.stem, f"demo/{path.name}", path.read_text("utf-8"))

    async def close(self):
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        await self.knowledge.close()
        await self.http.aclose()
        await self.store.close()

    async def submit(self, request: dict):
        async with self._submission_lock:
            if len(self.tasks) >= self.settings.max_active_tasks:
                raise TaskCapacityError
            task_id = uuid4().hex
            await self.store.create(task_id, {
                "id": task_id, "status": "queued", "node": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request": request, "result": None, "error": None,
                "execution_backend": "in-process", "storage_backend": self.store.backend,
            })
            await self.store.record(task_id, "queued", {"task_id": task_id})
            runner = asyncio.create_task(self._run(task_id, request))
            self.tasks[task_id] = runner
            runner.add_done_callback(lambda task: self.tasks.pop(task_id, None))
            return task_id

    async def _run(self, task_id, request):
        state = {"request": request}
        try:
            await self.store.record(task_id, "started", {}, {"status": "running"})
            async with asyncio.timeout(self.settings.task_timeout):
                async for update in self.workflow.graph.astream(
                    state, stream_mode="updates", config={"recursion_limit": 32},
                ):
                    for node, patch in update.items():
                        state.update(patch)
                        # Save partial results after each node for diagnosis and inspection.
                        await self.store.record(task_id, "progress", {
                            "node": node, "adjustment_round": state.get("plan", {}).get(
                                "adjustment_round", 0),
                        }, {"node": node, "partial": state})
            plan = state["plan"]
            status = "infeasible" if plan["state"] == "infeasible" else "completed"
            result = {
                "plan": plan, "citations": state["citations"], "summary": state["summary"],
                "data_mode": "mock", "embedding_mode": self.settings.embedding_mode,
            }
            await self.store.record(task_id, status, {"task_id": task_id, "status": status},
                                    {"status": status, "result": result})
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self.store.record(task_id, "cancelled", {}, {"status": "cancelled"})
            raise
        except Exception as error:
            # Do not expose provider response bodies, URLs or credentials through the API.
            logger.error("Task {} failed: {}", task_id, type(error).__name__)
            with contextlib.suppress(Exception):
                await self.store.record(task_id, "failed", {
                    "error": type(error).__name__,
                }, {"status": "failed", "error": type(error).__name__})

    async def event_stream(self, task_id, after=0):
        idle = 0
        while True:
            # Read snapshot before history: if it is terminal, its final event already exists.
            task = await self.store.get(task_id)
            if task is None:
                yield "event: expired\ndata: {}\n\n"
                return
            events = await self.store.events(task_id, after)
            for event in events:
                after = event["id"]
                yield (f"id: {after}\nevent: {event['event']}\ndata: "
                       f"{json.dumps(event['data'], ensure_ascii=False)}\n\n")
            if task["status"] in TERMINAL:
                return
            idle = 0 if events else idle + 1
            if idle >= 40:
                yield ": heartbeat\n\n"
                idle = 0
            await asyncio.sleep(0.25)
