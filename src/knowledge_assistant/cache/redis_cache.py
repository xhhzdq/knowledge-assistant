"""Redis 文档详情缓存 Adapter。"""

import json
import logging
from typing import Protocol, cast

from redis.exceptions import RedisError

from knowledge_assistant.cache.base import DocumentCache
from knowledge_assistant.models import Document, DocumentData

logger = logging.getLogger(__name__)


class RedisClient(Protocol):
    """redis-py 客户端中本项目实际依赖的最小同步接口。"""

    def get(self, name: str) -> str | bytes | None: ...

    def set(self, name: str, value: str, *, ex: int) -> object: ...

    def delete(self, *names: str) -> int: ...


class RedisDocumentCache(DocumentCache):
    """用 JSON 字符串缓存单文档详情，并在 Redis 故障时安全降级。"""

    DEFAULT_KEY_PREFIX = "knowledge-assistant:document:v1"

    def __init__(
        self,
        client: RedisClient,
        key_prefix: str = DEFAULT_KEY_PREFIX,
    ) -> None:
        normalized_prefix = key_prefix.strip().rstrip(":")
        if not normalized_prefix:
            raise ValueError("key_prefix must not be blank")
        self._client = client
        self.key_prefix = normalized_prefix

    def _key(self, document_id: str) -> str:
        """构造带应用名和版本号的缓存 Key。"""
        return f"{self.key_prefix}:{document_id}"

    def get(self, document_id: str) -> Document | None:
        """读取并反序列化缓存；异常或无效内容都按未命中处理。"""
        key = self._key(document_id)
        try:
            payload = self._client.get(key)
        except RedisError as exc:
            logger.warning("读取 Redis 缓存失败，降级查询数据库: key=%s error=%s", key, exc)
            return None

        if payload is None:
            logger.debug("Redis 缓存未命中: key=%s", key)
            return None

        try:
            decoded: object = json.loads(payload)
            data = self._validate_document_data(decoded)
            document = Document.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Redis 缓存内容无效，按未命中处理: key=%s error=%s", key, exc)
            self.delete(document_id)
            return None

        logger.debug("Redis 缓存命中: key=%s", key)
        return document

    def set(self, document: Document, ttl_seconds: int) -> None:
        """将文档序列化为 JSON，并用 EX 设置 TTL。"""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")

        key = self._key(document.id)
        payload = json.dumps(document.to_dict(), ensure_ascii=False, separators=(",", ":"))
        try:
            self._client.set(key, payload, ex=ttl_seconds)
        except RedisError as exc:
            logger.warning("写入 Redis 缓存失败，继续返回数据库结果: key=%s error=%s", key, exc)

    def delete(self, document_id: str) -> None:
        """主动使详情缓存失效；Redis 故障不阻断主业务。"""
        key = self._key(document_id)
        try:
            self._client.delete(key)
        except RedisError as exc:
            logger.warning("删除 Redis 缓存失败，等待 TTL 兜底: key=%s error=%s", key, exc)

    @staticmethod
    def _validate_document_data(value: object) -> DocumentData:
        """在进入领域模型前校验 Redis 中 JSON 的基本结构。"""
        if not isinstance(value, dict):
            raise ValueError("cached document must be a JSON object")

        string_fields = {
            "id",
            "name",
            "original_path",
            "stored_path",
            "file_type",
            "status",
            "created_at",
        }
        for field in string_fields:
            if not isinstance(value.get(field), str):
                raise ValueError(f"cached document field must be a string: {field}")

        file_size = value.get("file_size")
        if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
            raise ValueError("cached document file_size must be a non-negative integer")

        return cast("DocumentData", value)
