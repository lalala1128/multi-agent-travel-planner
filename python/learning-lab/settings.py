"""运行配置：本地学习与容器部署共用同一套环境变量。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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
    embedding_cache_dir: str | None
    rate_limit_requests: int
    rate_limit_window_seconds: int
    travel_provider: str
    allowed_hosts: list[str]
    hotelbeds_api_key: str | None
    hotelbeds_secret: str | None
    hotelbeds_base_url: str
    hotelbeds_client_cert: str | None
    hotelbeds_client_key: str | None
    hotelbeds_client_key_password: str | None
    hotelbeds_timeout_seconds: float


def load_settings() -> Settings:
    # 不能依赖某个 Agent 恰好先导入；所有配置读取都应自行加载项目 .env。
    # 默认不覆盖外部环境变量，便于容器和 Secret Manager 注入配置。
    load_dotenv(Path(__file__).resolve().parent / ".env")
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    ]
    allowed_hosts = [
        host.strip()
        for host in os.getenv("ALLOWED_HOSTS", "").split(",")
        if host.strip()
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
        embedding_cache_dir=os.getenv("EMBEDDING_CACHE_DIR") or None,
        rate_limit_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "60")),
        rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
        travel_provider=os.getenv("TRAVEL_PROVIDER", "demo").strip().lower(),
        allowed_hosts=allowed_hosts,
        hotelbeds_api_key=os.getenv("HOTELBEDS_API_KEY") or None,
        hotelbeds_secret=os.getenv("HOTELBEDS_SECRET") or None,
        hotelbeds_base_url=os.getenv("HOTELBEDS_BASE_URL", "https://api-mtls.test.hotelbeds.com"),
        hotelbeds_client_cert=os.getenv("HOTELBEDS_CLIENT_CERT") or None,
        hotelbeds_client_key=os.getenv("HOTELBEDS_CLIENT_KEY") or None,
        hotelbeds_client_key_password=os.getenv("HOTELBEDS_CLIENT_KEY_PASSWORD") or None,
        hotelbeds_timeout_seconds=float(os.getenv("HOTELBEDS_TIMEOUT_SECONDS", "15")),
    )
