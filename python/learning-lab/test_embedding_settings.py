from pathlib import Path

from knowledge_agent import KnowledgeAgent


def test_knowledge_agent_can_reuse_external_embedding_cache(monkeypatch, tmp_path):
    shared_cache = tmp_path / "shared-model-cache"
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", str(shared_cache))
    agent = KnowledgeAgent(cache=object())
    assert agent.model_cache_dir == Path(shared_cache)
