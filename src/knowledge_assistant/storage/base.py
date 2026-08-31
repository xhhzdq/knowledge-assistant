"""文档原文件存储的抽象接口。"""

from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredObject:
    """一次存储操作返回的对象信息。"""

    object_key: str
    file_size: int
    etag: str | None = None


class DocumentStorage(Protocol):
    """定义 Service 保存和删除原文件所需的最小能力。"""

    def save(self, filename: str, source: BinaryIO) -> StoredObject:
        """保存文件流并返回对象 Key、大小等信息。"""
        ...

    def delete(self, object_key: str) -> None:
        """删除指定对象；对象不存在时由具体实现定义幂等行为。"""
        ...

    def exists(self, object_key: str) -> bool:
        """判断指定对象是否存在。"""
        ...
