"""创建 Qdrant 客户端：本地路径或远程服务二选一。"""

from pathlib import Path

from qdrant_client import QdrantClient

from settings import load_settings


def create_qdrant_client(base_dir: Path) -> QdrantClient:
    settings = load_settings()
    if settings.qdrant_url:
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout_seconds,
        )
    return QdrantClient(path=str(base_dir / "data" / "qdrant_demo"))
