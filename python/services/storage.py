"""Explicit memory/Redis backends. Redis failures never silently fork task history."""

import asyncio
import copy
import json
import time
from typing import Any

from redis.asyncio import Redis

TERMINAL = {"completed", "infeasible", "failed", "cancelled"}


class MemoryStore:
    backend = "memory"

    def __init__(self, ttl: int = 86400):
        self.ttl = ttl
        self._tasks: dict[str, tuple[float, dict]] = {}
        self._events: dict[str, list[dict]] = {}
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def ping(self):
        return True

    async def close(self):
        pass

    async def create(self, task_id: str, payload: dict):
        async with self._lock:
            for expired_id, (deadline, _) in list(self._tasks.items()):
                if deadline <= time.monotonic():
                    self._tasks.pop(expired_id, None)
                    self._events.pop(expired_id, None)
            self._tasks[task_id] = (time.monotonic() + self.ttl, copy.deepcopy(payload))
            self._events[task_id] = []

    def _get(self, task_id):
        item = self._tasks.get(task_id)
        if not item:
            return None
        if item[0] <= time.monotonic():
            self._tasks.pop(task_id, None)
            self._events.pop(task_id, None)
            return None
        return item[1]

    async def get(self, task_id: str):
        async with self._lock:
            return copy.deepcopy(self._get(task_id))

    async def record(self, task_id: str, kind: str, data: dict, patch: dict | None = None):
        async with self._lock:
            task = self._get(task_id)
            if task is None:
                raise KeyError(task_id)
            task.update(copy.deepcopy(patch or {}))
            events = self._events[task_id]
            event = {"id": len(events) + 1, "event": kind, "data": copy.deepcopy(data)}
            events.append(event)
            self._tasks[task_id] = (time.monotonic() + self.ttl, task)
            return event

    async def events(self, task_id: str, after: int):
        async with self._lock:
            if self._get(task_id) is None:
                return []
            return copy.deepcopy(self._events[task_id][after:])

    async def cache_get(self, key: str):
        item = self._cache.get(key)
        if item and item[0] > time.monotonic():
            return copy.deepcopy(item[1])
        self._cache.pop(key, None)
        return None

    async def cache_set(self, key: str, value: Any, ttl: int):
        for expired_key, (deadline, _) in list(self._cache.items()):
            if deadline <= time.monotonic():
                self._cache.pop(expired_key, None)
        self._cache[key] = (time.monotonic() + ttl, copy.deepcopy(value))


# One atomic operation updates task snapshot, assigns event ID, and appends replay history.
RECORD_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return redis.error_reply('task expired') end
local patch = cjson.decode(ARGV[1])
for k,v in pairs(patch) do redis.call('HSET', KEYS[1], k, v) end
local id = redis.call('LLEN', KEYS[2]) + 1
local encoded = '{"id":' .. id .. ',"event":' .. cjson.encode(ARGV[2]) .. ',"data":' .. ARGV[3] .. '}'
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('RPUSH', KEYS[2], encoded)
redis.call('EXPIRE', KEYS[2], ARGV[4])
return encoded
"""


class RedisStore:
    backend = "redis"

    def __init__(self, url: str = "", ttl: int = 86400, client=None):
        self.client = client or Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
        )
        self.ttl = ttl

    @staticmethod
    def keys(task_id):
        # Hash tags keep both keys in one slot on Redis Cluster.
        return f"travel:{{{task_id}}}:task", f"travel:{{{task_id}}}:events"

    async def ping(self):
        return await self.client.ping()

    async def close(self):
        await self.client.aclose()

    async def create(self, task_id, payload):
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.hset(self.keys(task_id)[0], mapping={k: json.dumps(v) for k, v in payload.items()})
            pipe.expire(self.keys(task_id)[0], self.ttl)
            await pipe.execute()

    async def get(self, task_id):
        raw = await self.client.hgetall(self.keys(task_id)[0])
        return {key: json.loads(value) for key, value in raw.items()} if raw else None

    async def record(self, task_id, kind, data, patch=None):
        raw = await self.client.eval(
            RECORD_LUA, 2, *self.keys(task_id),
            json.dumps({k: json.dumps(v) for k, v in (patch or {}).items()}), kind,
            json.dumps(data), self.ttl,
        )
        return json.loads(raw)

    async def events(self, task_id, after):
        return [json.loads(raw) for raw in await self.client.lrange(self.keys(task_id)[1], after, -1)]

    async def cache_get(self, key):
        raw = await self.client.get(f"travel:cache:{key}")
        return json.loads(raw) if raw else None

    async def cache_set(self, key, value, ttl):
        await self.client.set(f"travel:cache:{key}", json.dumps(value), ex=ttl)
