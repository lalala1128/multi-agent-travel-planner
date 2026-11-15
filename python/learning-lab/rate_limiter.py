"""基于 Redis 的固定窗口 API 限流。"""

import hashlib

from redis.exceptions import RedisError


RATE_LIMIT_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)


class RateLimiter:
    def __init__(self, client, max_requests: int, window_seconds: int):
        if max_requests < 0 or window_seconds <= 0:
            raise ValueError("限流次数不能为负数，窗口必须大于零")
        self.client = client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    @staticmethod
    def key(subject: str) -> str:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return f"travel-agent-lab:rate:{digest}"

    def check(self, subject: str):
        if self.max_requests == 0:
            return
        try:
            count, ttl = self.client.eval(
                RATE_LIMIT_LUA,
                1,
                self.key(subject),
                self.window_seconds,
            )
        except RedisError:
            raise
        if count > self.max_requests:
            raise RateLimitExceeded(ttl)
