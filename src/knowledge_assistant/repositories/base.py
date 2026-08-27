"""文档 Repository 的抽象接口。"""

from typing import Protocol

from knowledge_assistant.models import Document


class DocumentRepository(Protocol):
    """定义 Service 所依赖的最小持久化能力。"""

    def list_all(self) -> list[Document]:
        """返回全部文档。"""
        ...

    def list_page(self, offset: int, limit: int) -> list[Document]:
        """分页返回文档。"""
        ...

    def count(self) -> int:
        """返回文档总数。"""
        ...

    def get_by_id(self, document_id: str) -> Document:
        """按 ID 返回一个文档。"""
        ...

    def add(self, document: Document) -> None:
        """保存一个文档。"""
        ...

    def update(self, document: Document) -> Document:
        """更新并返回一个文档。"""
        ...

    def delete(self, document_id: str) -> Document:
        """删除并返回一个文档。"""
        ...
