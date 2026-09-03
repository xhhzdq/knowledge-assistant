"""本地文件存储 Adapter。

将 DocumentService 当前的本地文件操作迁移到此模块，作为存储抽象的默认实现。
CLI 和单元测试继续使用此实现，API 在第三周会切换到 MinIO。
"""
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from knowledge_assistant.exceptions import StorageError
from knowledge_assistant.storage.base import DocumentStorage, StoredObject


class LocalDocumentStorage(DocumentStorage):
    """使用本地文件系统保存文档原文件。"""

    def __init__(self, upload_dir: str | Path, max_file_size: int = 10 * 1024 * 1024) -> None:
        """初始化本地存储。

        Args:
            upload_dir: 上传文件根目录
            max_file_size: 最大文件大小（字节），默认 10MB
        """
        self.upload_dir = Path(upload_dir).resolve()
        if max_file_size <= 0:
            raise ValueError("max_file_size must be greater than zero")
        self.max_file_size = max_file_size
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _generate_object_key(self, filename: str) -> str:
        """生成安全的对象 Key。

        使用 UUID 避免文件名冲突和路径遍历攻击。

        Args:
            filename: 原始文件名

        Returns:
            对象 Key，格式为 documents/{uuid}.{ext}
        """
        ext = Path(filename).suffix.lower()
        if not ext:
            ext = ".bin"
        return f"documents/{uuid4().hex}{ext}"

    def _resolve_object_path(self, object_key: str) -> Path:
        """把对象 Key 安全解析为上传目录内的绝对路径。"""
        key_path = Path(object_key)
        candidate = key_path if key_path.is_absolute() else self.upload_dir / key_path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.upload_dir)
        except ValueError as exc:
            raise StorageError("Refusing to access a file outside the uploads directory") from exc
        return resolved

    def save(self, filename: str, source: BinaryIO) -> StoredObject:
        """保存文件流并返回对象信息。

        Args:
            filename: 原始文件名（用于提取扩展名）
            source: 文件流

        Returns:
            StoredObject: 包含对象 Key 和文件大小

        Raises:
            ValueError: 文件大小超过限制
            OSError: 文件写入失败
        """
        object_key = self._generate_object_key(filename)
        file_path = self._resolve_object_path(object_key)

        # 确保子目录存在（例如 documents/）
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 分块读取并写入，同时检查大小
        file_size = 0
        chunk_size = 8192

        try:
            with file_path.open("wb") as dest:
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > self.max_file_size:
                        raise ValueError(
                            f"File size {file_size} exceeds limit {self.max_file_size}"
                        )
                    dest.write(chunk)
        except (ValueError, OSError) as exc:
            # 确保失败时不留残留文件
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, ValueError):
                raise
            raise StorageError(f"Unable to save local object: {object_key}") from exc

        return StoredObject(
            object_key=object_key,
            file_size=file_size,
        )

    def read(self, object_key: str) -> bytes:
        """读取上传目录内的对象，包括合法的空文件。"""
        file_path = self._resolve_object_path(object_key)
        try:
            return file_path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Local object not found: {object_key}") from exc
        except OSError as exc:
            raise StorageError(f"Unable to read local object: {object_key}") from exc

    def delete(self, object_key: str) -> None:
        """删除指定对象；对象不存在时不报错（幂等）。

        Args:
            object_key: 对象 Key
        """
        file_path = self._resolve_object_path(object_key)
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Unable to delete local object: {object_key}") from exc

    def exists(self, object_key: str) -> bool:
        """判断指定对象是否存在。

        Args:
            object_key: 对象 Key

        Returns:
            bool: 对象是否存在
        """
        file_path = self._resolve_object_path(object_key)
        try:
            return file_path.is_file()
        except OSError as exc:
            raise StorageError(f"Unable to inspect local object: {object_key}") from exc
