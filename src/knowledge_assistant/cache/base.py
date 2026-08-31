"""文档缓存的抽象接口。"""

from typing import Protocol

from knowledge_assistant.models import Document


class DocumentCache(Protocol):
    """定义文档详情 Cache Aside 所需的最小能力。"""

    def get(self, document_id: str) -> Document | None:
        """读取缓存；未命中时返回 None。"""
        ...

    def set(self, document: Document, ttl_seconds: int) -> None:
        """写入文档缓存并设置生存时间。"""
        ...

    def delete(self, document_id: str) -> None:
        """使指定文档缓存失效。"""
        ...
