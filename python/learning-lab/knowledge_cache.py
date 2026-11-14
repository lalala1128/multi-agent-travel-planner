"""知识检索结果缓存；Redis 故障时继续执行原检索。"""

import hashlib
import json
import logging

from redis import Redis
from redis.exceptions import RedisError

from schemas import KnowledgeChunk


logger = logging.getLogger(__name__)


class KnowledgeCache:
    def __init__(self, client=None, ttl: int = 600):
        if ttl <= 0:
            raise ValueError("缓存有效期必须大于零")

        self.ttl = ttl
        self.client = client if client is not None else Redis(
            host="127.0.0.1",
            port=6380,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @staticmethod
    def make_key(context: dict) -> str:
        # 固定字段顺序，确保相同参数总能生成同一个键。
        encoded = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"travel-agent-lab:knowledge:{digest}"

    def get(self, context: dict) -> list[dict] | None:
        try:
            raw = self.client.get(self.make_key(context))
        except RedisError:
            logger.warning("Redis 缓存读取失败，继续执行知识检索")
            return None

        if raw is None:
            return None

        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("缓存结果必须是列表")

            results = []
            for item in data:
                chunk = KnowledgeChunk.model_validate(item)
                results.append(chunk.model_dump())
            return results
        except (ValueError, TypeError):
            logger.warning("知识缓存格式无效，重新执行检索")
            return None

    def set(self, context: dict, results: list[dict]):
        encoded = json.dumps(results, ensure_ascii=False, allow_nan=False)
        try:
            self.client.set(self.make_key(context), encoded, ex=self.ttl)
        except RedisError:
            logger.warning("Redis 缓存写入失败，保留本次检索结果")

    def close(self):
        self.client.close()
