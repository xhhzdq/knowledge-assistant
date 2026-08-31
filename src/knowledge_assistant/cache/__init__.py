"""可丢失、可重新生成的应用缓存接口及其实现。"""

from knowledge_assistant.cache.base import DocumentCache
from knowledge_assistant.cache.redis_cache import RedisDocumentCache

__all__ = ["DocumentCache", "RedisDocumentCache"]
