from unittest.mock import Mock

import fakeredis
import pytest
from redis.exceptions import ConnectionError

from knowledge_cache import KnowledgeCache


@pytest.fixture
def context():
    return {
        "city": "首尔",
        "question": "美食建议",
        "model": "BAAI/bge-small-zh-v1.5",
        "collection": "travel_knowledge",
        "top_k": 3,
        "score_threshold": 0.4,
        "knowledge_version": "v1",
    }


@pytest.fixture
def results():
    return [{
        "id": "chunk-1", "city": "首尔", "source": "首尔.md",
        "chunk_index": 1, "text": "可以体验当地市场。", "score": 0.8,
    }]


def test_json_round_trip_and_ttl(context, results):
    client = fakeredis.FakeRedis(decode_responses=True)
    cache = KnowledgeCache(client=client)
    try:
        assert cache.get(context) is None
        cache.set(context, results)
        assert cache.get(context) == results
        assert 0 < client.ttl(cache.make_key(context)) <= 600
        client.delete(cache.make_key(context))
        assert cache.get(context) is None
    finally:
        cache.close()


def test_empty_results_are_a_cache_hit(context):
    cache = KnowledgeCache(client=fakeredis.FakeRedis(decode_responses=True))
    try:
        cache.set(context, [])
        assert cache.get(context) == []
        assert cache.get(context) is not None
    finally:
        cache.close()


def test_cache_preserves_rerank_observability_fields(context, results):
    enriched = [{
        **results[0],
        "vector_score": 0.7,
        "keyword_score": 0.5,
        "rerank_score": 0.66,
    }]
    cache = KnowledgeCache(client=fakeredis.FakeRedis(decode_responses=True))
    try:
        cache.set(context, enriched)
        assert cache.get(context) == enriched
    finally:
        cache.close()


@pytest.mark.parametrize("field,value", [
    ("city", "东京"), ("question", "文化建议"), ("model", "another-model"),
    ("collection", "another-collection"), ("top_k", 1),
    ("score_threshold", 0.8), ("knowledge_version", "v2"),
])
def test_retrieval_settings_are_part_of_key(context, field, value):
    assert KnowledgeCache.make_key(context) != KnowledgeCache.make_key({**context, field: value})


def test_key_does_not_depend_on_dictionary_order(context):
    reversed_context = dict(reversed(list(context.items())))
    assert KnowledgeCache.make_key(context) == KnowledgeCache.make_key(reversed_context)


@pytest.mark.parametrize("raw", ["not JSON", "{}", '[{"id":"missing-fields"}]'])
def test_invalid_cache_data_is_a_miss(context, raw):
    client = fakeredis.FakeRedis(decode_responses=True)
    cache = KnowledgeCache(client=client)
    try:
        client.set(cache.make_key(context), raw)
        assert cache.get(context) is None
    finally:
        cache.close()


def test_redis_failures_do_not_raise_into_retrieval(context, results):
    client = Mock()
    client.get.side_effect = ConnectionError("模拟 Redis 故障")
    client.set.side_effect = ConnectionError("模拟 Redis 故障")
    cache = KnowledgeCache(client=client)
    assert cache.get(context) is None
    cache.set(context, results)


def test_invalid_ttl_is_rejected():
    with pytest.raises(ValueError):
        KnowledgeCache(client=Mock(), ttl=0)
