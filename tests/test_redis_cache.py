"""RedisDocumentCache 的纯单元测试，不连接真实 Redis。"""

import json

import pytest
from redis.exceptions import ConnectionError

from knowledge_assistant.cache.redis_cache import RedisDocumentCache
from knowledge_assistant.models import Document


class FakeRedisClient:
    """记录字符串值和 TTL 的最小 Redis 假客户端。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str, *, ex: int) -> bool:
        self.values[name] = value
        self.ttls[name] = ex
        return True

    def delete(self, *names: str) -> int:
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                self.values.pop(name)
                self.ttls.pop(name, None)
        return deleted


class FailingRedisClient(FakeRedisClient):
    """模拟 Redis 网络不可用。"""

    def get(self, name: str) -> str | None:
        raise ConnectionError("redis unavailable")

    def set(self, name: str, value: str, *, ex: int) -> bool:
        raise ConnectionError("redis unavailable")

    def delete(self, *names: str) -> int:
        raise ConnectionError("redis unavailable")


def build_document() -> Document:
    """创建字段稳定的测试文档。"""
    return Document(
        id="e752b97e-5810-4c02-841f-5925dc0cd92d",
        name="Redis学习.md",
        original_path="Redis学习.md",
        stored_path="documents/example.md",
        file_type=".md",
        file_size=128,
        status="ready",
        created_at="2026-08-31T00:00:00+00:00",
    )


def test_set_uses_versioned_key_json_and_ttl() -> None:
    client = FakeRedisClient()
    cache = RedisDocumentCache(client)
    document = build_document()

    cache.set(document, ttl_seconds=300)

    key = f"knowledge-assistant:document:v1:{document.id}"
    assert json.loads(client.values[key]) == document.to_dict()
    assert client.ttls[key] == 300


def test_get_returns_none_for_cache_miss() -> None:
    cache = RedisDocumentCache(FakeRedisClient())

    assert cache.get("missing-id") is None


def test_get_restores_cached_document() -> None:
    client = FakeRedisClient()
    cache = RedisDocumentCache(client)
    document = build_document()
    cache.set(document, ttl_seconds=60)

    assert cache.get(document.id) == document


def test_delete_invalidates_cached_document() -> None:
    client = FakeRedisClient()
    cache = RedisDocumentCache(client)
    document = build_document()
    cache.set(document, ttl_seconds=60)

    cache.delete(document.id)

    assert cache.get(document.id) is None


def test_invalid_json_is_deleted_and_treated_as_miss() -> None:
    client = FakeRedisClient()
    cache = RedisDocumentCache(client)
    key = "knowledge-assistant:document:v1:broken"
    client.values[key] = "not-json"

    assert cache.get("broken") is None
    assert key not in client.values


def test_invalid_document_shape_is_deleted_and_treated_as_miss() -> None:
    client = FakeRedisClient()
    cache = RedisDocumentCache(client)
    key = "knowledge-assistant:document:v1:broken"
    client.values[key] = '{"id":"broken"}'

    assert cache.get("broken") is None
    assert key not in client.values


def test_redis_failure_degrades_without_raising() -> None:
    cache = RedisDocumentCache(FailingRedisClient())
    document = build_document()

    assert cache.get(document.id) is None
    cache.set(document, ttl_seconds=300)
    cache.delete(document.id)


def test_rejects_invalid_ttl_and_key_prefix() -> None:
    client = FakeRedisClient()
    document = build_document()

    with pytest.raises(ValueError, match="key_prefix"):
        RedisDocumentCache(client, key_prefix=" ")
    with pytest.raises(ValueError, match="ttl_seconds"):
        RedisDocumentCache(client).set(document, ttl_seconds=0)
