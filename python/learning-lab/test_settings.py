from settings import load_settings


def test_explicit_environment_overrides_dotenv(monkeypatch):
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "C:/injected/cache")
    assert load_settings().embedding_cache_dir == "C:/injected/cache"
