"""运行配置：本地学习与容器部署共用同一套环境变量。"""

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    redis_host: str
    redis_port: int
    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_timeout_seconds: float
    task_ttl_seconds: int
    cache_ttl_seconds: int
    task_max_pending: int
    api_key: str | None
    cors_origins: list[str]
    embedding_local_files_only: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int


def load_settings() -> Settings:
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return Settings(
        redis_host=os.getenv("REDIS_HOST", "127.0.0.1"),
        redis_port=int(os.getenv("REDIS_PORT", "6380")),
        qdrant_url=os.getenv("QDRANT_URL") or None,
        qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
        qdrant_timeout_seconds=float(os.getenv("QDRANT_TIMEOUT_SECONDS", "5")),
        task_ttl_seconds=int(os.getenv("TASK_TTL_SECONDS", "86400")),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "600")),
        task_max_pending=int(os.getenv("TASK_MAX_PENDING", "8")),
        api_key=os.getenv("API_KEY") or None,
        cors_origins=origins,
        embedding_local_files_only=env_bool("EMBEDDING_LOCAL_FILES_ONLY", True),
        rate_limit_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "60")),
        rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
    )
