"""文档原文件存储接口及其实现。"""

from knowledge_assistant.storage.base import DocumentStorage, StoredObject
from knowledge_assistant.storage.local_storage import LocalDocumentStorage
from knowledge_assistant.storage.minio_storage import MinioDocumentStorage

__all__ = [
    "DocumentStorage",
    "LocalDocumentStorage",
    "MinioDocumentStorage",
    "StoredObject",
]
