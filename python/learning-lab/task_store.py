"""任务快照与事件流存储。"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from redis import Redis

from schemas import TaskEvent, TaskRecord, TravelRequest
from settings import load_settings


CREATE_TASK_LUA = """
if redis.call("EXISTS", KEYS[1]) == 1 then
    return 0
end

redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[3])
redis.call("SET", KEYS[2], 1, "EX", ARGV[3])
redis.call("RPUSH", KEYS[3], ARGV[2])
redis.call("EXPIRE", KEYS[3], ARGV[3])

return 1
"""


SAVE_WITH_EVENT_LUA = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return nil
end

local event_id = redis.call("INCR", KEYS[2])
local event = cjson.decode(ARGV[2])
event["id"] = event_id

redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[3], "XX")
redis.call("RPUSH", KEYS[3], cjson.encode(event))
redis.call("EXPIRE", KEYS[2], ARGV[3])
redis.call("EXPIRE", KEYS[3], ARGV[3])

return cjson.encode(event)
"""


APPEND_EVENT_LUA = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return nil
end

local event_id = redis.call("INCR", KEYS[2])
local event = cjson.decode(ARGV[1])
event["id"] = event_id

redis.call("RPUSH", KEYS[3], cjson.encode(event))
-- 进度事件也会刷新三个相关键的生存时间，防止长任务中途过期。
redis.call("EXPIRE", KEYS[1], ARGV[2])
redis.call("EXPIRE", KEYS[2], ARGV[2])
redis.call("EXPIRE", KEYS[3], ARGV[2])

return cjson.encode(event)
"""


class TaskStore:
    def __init__(self, client=None, ttl: int | None = None):
        settings = load_settings()
        ttl = settings.task_ttl_seconds if ttl is None else ttl
        if ttl <= 0:
            raise ValueError("任务有效期必须大于零")

        self.ttl = ttl
        self.client = client if client is not None else Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @staticmethod
    def key(task_id: str):
        return f"travel-agent-lab:task:{task_id}"

    @staticmethod
    def event_sequence_key(task_id: str):
        return f"travel-agent-lab:task:{task_id}:event-sequence"

    @staticmethod
    def events_key(task_id: str):
        return f"travel-agent-lab:task:{task_id}:events"

    def create(self, request: TravelRequest) -> TaskRecord:
        now = datetime.now(timezone.utc)
        record = TaskRecord(
            id=str(uuid4()),
            request=request,
            created_at=now,
            updated_at=now,
        )

        queued_event = TaskEvent(
            id=1,
            event="queued",
            data={"message": "任务已创建，等待执行"},
            created_at=now,
        )

        created = self.client.eval(
            CREATE_TASK_LUA,
            3,
            self.key(record.id),
            self.event_sequence_key(record.id),
            self.events_key(record.id),
            record.model_dump_json(),
            queued_event.model_dump_json(),
            self.ttl,
        )
        if not created:
            raise RuntimeError("任务 ID 已存在")

        return record

    def save_with_event(
        self,
        record: TaskRecord,
        event: str,
        data: dict | None = None,
    ) -> TaskEvent:
        now = datetime.now(timezone.utc)
        record.updated_at = now

        # 先借助 Pydantic 校验事件名是否合法。
        event_without_id = TaskEvent(
            id=1,
            event=event,
            data=data or {},
            created_at=now,
        ).model_dump(mode="json", exclude={"id"})

        raw_event = self.client.eval(
            SAVE_WITH_EVENT_LUA,
            3,
            self.key(record.id),
            self.event_sequence_key(record.id),
            self.events_key(record.id),
            record.model_dump_json(),
            json.dumps(event_without_id, ensure_ascii=False),
            self.ttl,
        )
        if raw_event is None:
            raise LookupError("任务记录已过期，无法更新")

        return TaskEvent.model_validate_json(raw_event)

    def append_event(
        self,
        task_id: str,
        event: str,
        data: dict | None = None,
    ) -> TaskEvent:
        """追加非状态迁移事件，例如工作流节点进度。"""
        now = datetime.now(timezone.utc)
        event_without_id = TaskEvent(
            id=1,
            event=event,
            data=data or {},
            created_at=now,
        ).model_dump(mode="json", exclude={"id"})

        raw_event = self.client.eval(
            APPEND_EVENT_LUA,
            3,
            self.key(task_id),
            self.event_sequence_key(task_id),
            self.events_key(task_id),
            json.dumps(event_without_id, ensure_ascii=False),
            self.ttl,
        )
        if raw_event is None:
            raise LookupError("任务记录已过期，无法追加事件")

        return TaskEvent.model_validate_json(raw_event)

    def get(self, task_id: str) -> TaskRecord | None:
        raw = self.client.get(self.key(task_id))
        return TaskRecord.model_validate_json(raw) if raw is not None else None

    def list_events(self, task_id: str, after_id: int = 0) -> list[TaskEvent]:
        if after_id < 0:
            raise ValueError("after_id 不能小于零")

        # 事件 ID 从 1 开始，Redis List 下标从 0 开始。
        raw_events = self.client.lrange(
            self.events_key(task_id),
            after_id,
            -1,
        )
        return [TaskEvent.model_validate_json(raw) for raw in raw_events]

    def list_unfinished(self) -> list[TaskRecord]:
        """扫描任务快照键，不把事件列表和序号键误判为任务。"""
        prefix = "travel-agent-lab:task:"
        records = []
        for key in self.client.scan_iter(match=f"{prefix}*"):
            suffix = key.removeprefix(prefix)
            if ":" in suffix:
                continue
            record = self.get(suffix)
            if record is not None and record.status in {"queued", "running"}:
                records.append(record)
        return records

    def close(self):
        self.client.close()
