"""MinIO 对象存储 Adapter。"""

import logging
import mimetypes
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Protocol, cast
from uuid import uuid4

from minio.error import MinioException, S3Error
from urllib3.exceptions import HTTPError

from knowledge_assistant.exceptions import StorageError
from knowledge_assistant.storage.base import DocumentStorage, StoredObject

logger = logging.getLogger(__name__)


class ObjectWriteResult(Protocol):
    """只描述上传结果中本项目实际使用的字段。"""

    etag: str


class ObjectReadResponse(Protocol):
    """MinIO ``get_object`` 返回的流式 HTTP 响应最小接口。"""

    def read(self) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class MinioClient(Protocol):
    """MinIO SDK 客户端的最小接口，便于用假客户端做单元测试。"""

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> ObjectWriteResult: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...

    def stat_object(self, bucket_name: str, object_name: str) -> object: ...

    def get_object(self, bucket_name: str, object_name: str) -> ObjectReadResponse: ...


class MinioDocumentStorage(DocumentStorage):
    """使用一个私有 MinIO Bucket 保存文档原文件。"""

    def __init__(
        self,
        client: MinioClient,
        bucket_name: str,
        max_file_size: int = 10 * 1024 * 1024,
    ) -> None:
        """保存客户端和 Bucket 配置，不在构造阶段发起网络请求。"""
        if not bucket_name.strip():
            raise ValueError("bucket_name must not be blank")
        if max_file_size <= 0:
            raise ValueError("max_file_size must be greater than zero")
        self._client = client
        self.bucket_name = bucket_name
        self.max_file_size = max_file_size

    @staticmethod
    def _generate_object_key(filename: str) -> str:
        """使用 UUID 生成对象 Key，避免重名和路径穿越。"""
        # PurePosixPath 只提取扩展名，不会把用户目录带进对象 Key。
        extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower() or ".bin"
        return f"documents/{uuid4().hex}{extension}"

    def save(self, filename: str, source: BinaryIO) -> StoredObject:
        """校验大小后把文件流上传到 MinIO。"""
        object_key = self._generate_object_key(filename)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_size = 0

        # 上传前先暂存并计数，防止超限文件已经进入 MinIO。
        with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:
            while True:
                chunk = source.read(8192)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > self.max_file_size:
                    raise ValueError(
                        f"File size {file_size} exceeds limit {self.max_file_size}"
                    )
                staged.write(chunk)
            staged.seek(0)

            try:
                result = self._client.put_object(
                    self.bucket_name,
                    object_key,
                    cast("BinaryIO", staged),
                    file_size,
                    content_type=content_type,
                )
            except (MinioException, HTTPError, OSError) as exc:
                raise StorageError(f"Unable to upload MinIO object: {object_key}") from exc

        return StoredObject(
            object_key=object_key,
            file_size=file_size,
            etag=result.etag,
        )

    def read(self, object_key: str) -> bytes:
        """读取完整对象，并在所有响应路径释放 HTTP 连接。"""
        response: ObjectReadResponse | None = None
        try:
            response = self._client.get_object(self.bucket_name, object_key)
            return response.read()
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise StorageError(f"MinIO object not found: {object_key}") from exc
            raise StorageError(f"Unable to read MinIO object: {object_key}") from exc
        except (MinioException, HTTPError, OSError) as exc:
            raise StorageError(f"Unable to read MinIO object: {object_key}") from exc
        finally:
            if response is not None:
                self._release_response(response, object_key)

    @staticmethod
    def _release_response(response: ObjectReadResponse, object_key: str) -> None:
        """尽最大努力关闭响应并归还连接，且不覆盖原始读取异常。"""
        try:
            response.close()
        except (HTTPError, OSError):
            logger.warning("关闭 MinIO 响应失败: object_key=%s", object_key)
        try:
            response.release_conn()
        except (HTTPError, OSError):
            logger.warning("释放 MinIO 连接失败: object_key=%s", object_key)

    def delete(self, object_key: str) -> None:
        """删除对象；S3 的单对象删除对不存在的 Key 保持幂等。"""
        try:
            self._client.remove_object(self.bucket_name, object_key)
        except (MinioException, HTTPError, OSError) as exc:
            raise StorageError(f"Unable to delete MinIO object: {object_key}") from exc

    def exists(self, object_key: str) -> bool:
        """通过读取对象元数据判断对象是否存在。"""
        try:
            self._client.stat_object(self.bucket_name, object_key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return False
            raise StorageError(f"Unable to inspect MinIO object: {object_key}") from exc
        except (MinioException, HTTPError, OSError) as exc:
            raise StorageError(f"Unable to inspect MinIO object: {object_key}") from exc
        return True
