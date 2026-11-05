from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator
import os

ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseModel):
    redis_url: str = ""
    task_ttl: int = Field(default=86400, ge=60)
    cache_ttl: int = Field(default=600, ge=1)
    task_timeout: float = Field(default=180, gt=0)
    tool_timeout: float = Field(default=15, gt=0)
    tool_attempts: int = Field(default=2, ge=1, le=5)
    max_adjustments: int = Field(default=3, ge=0, le=3)
    qdrant_url: str = ""
    qdrant_path: str = str(ROOT / "data" / "qdrant")
    embedding_mode: Literal["hash", "http"] = "hash"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dimensions: int = Field(default=256, ge=8)
    generation_mode: Literal["template", "llm"] = "template"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    api_key: str = ""
    max_active_tasks: int = Field(default=16, ge=1)
    demo_seed: bool = True

    @model_validator(mode="after")
    def check_credentials(self):
        if self.embedding_mode == "http" and not (
            self.embedding_base_url and self.embedding_api_key
        ):
            raise ValueError("HTTP embeddings require EMBEDDING_BASE_URL and EMBEDDING_API_KEY")
        if self.generation_mode == "llm" and not self.llm_api_key:
            raise ValueError("LLM generation requires LLM_API_KEY")
        return self

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls.model_validate({
            name: os.environ[name.upper()]
            for name in cls.model_fields
            if name.upper() in os.environ
        })
