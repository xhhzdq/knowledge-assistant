"""MinioDocumentStorage 的纯单元测试，不连接真实服务器。"""

from io import BytesIO
from typing import BinaryIO, cast

import pytest
from minio.error import S3Error

from knowledge_assistant.exceptions import StorageError
from knowledge_assistant.storage.minio_storage import MinioDocumentStorage


class FakeWriteResult:
    """模拟 MinIO SDK 的上传结果。"""

    etag = "fake-etag"


class FakeMinioClient:
    """只在内存中记录对象的 MinIO 假客户端。"""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.last_content_type: str | None = None

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> FakeWriteResult:
        self.objects[(bucket_name, object_name)] = data.read(length)
        self.last_content_type = content_type
        return FakeWriteResult()

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.objects.pop((bucket_name, object_name), None)

    def stat_object(self, bucket_name: str, object_name: str) -> object:
        if (bucket_name, object_name) not in self.objects:
            raise S3Error(
                cast("object", object()),
                "NoSuchKey",
                "missing",
                object_name,
                "request-id",
                "host-id",
                bucket_name,
                object_name,
            )
        return object()


@pytest.fixture
def client() -> FakeMinioClient:
    return FakeMinioClient()


@pytest.fixture
def storage(client: FakeMinioClient) -> MinioDocumentStorage:
    return MinioDocumentStorage(client, "knowledge", max_file_size=1024)


def test_save_uploads_stream_and_returns_object_info(
    storage: MinioDocumentStorage,
    client: FakeMinioClient,
) -> None:
    content = b"MinIO learning content"

    result = storage.save("guide.PDF", BytesIO(content))

    assert result.object_key.startswith("documents/")
    assert result.object_key.endswith(".pdf")
    assert result.file_size == len(content)
    assert result.etag == "fake-etag"
    assert client.objects[("knowledge", result.object_key)] == content
    assert client.last_content_type == "application/pdf"


def test_save_rejects_oversized_file_before_upload(
    storage: MinioDocumentStorage,
    client: FakeMinioClient,
) -> None:
    with pytest.raises(ValueError, match="exceeds limit"):
        storage.save("large.txt", BytesIO(b"x" * 1025))

    assert client.objects == {}


def test_exists_and_delete_are_idempotent(
    storage: MinioDocumentStorage,
) -> None:
    result = storage.save("guide.txt", BytesIO(b"content"))
    assert storage.exists(result.object_key) is True

    storage.delete(result.object_key)
    storage.delete(result.object_key)

    assert storage.exists(result.object_key) is False


def test_generates_different_keys_for_same_filename(storage: MinioDocumentStorage) -> None:
    first = storage.save("guide.txt", BytesIO(b"first"))
    second = storage.save("guide.txt", BytesIO(b"second"))

    assert first.object_key != second.object_key


def test_rejects_invalid_constructor_values(client: FakeMinioClient) -> None:
    with pytest.raises(ValueError, match="bucket_name"):
        MinioDocumentStorage(client, " ")
    with pytest.raises(ValueError, match="max_file_size"):
        MinioDocumentStorage(client, "knowledge", max_file_size=0)


class FailingMinioClient(FakeMinioClient):
    """模拟连接 MinIO 时发生的操作系统网络异常。"""

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> FakeWriteResult:
        raise OSError("network unavailable")


def test_sdk_failure_is_converted_to_storage_error() -> None:
    storage = MinioDocumentStorage(FailingMinioClient(), "knowledge")

    with pytest.raises(StorageError, match="Unable to upload MinIO object"):
        storage.save("guide.txt", BytesIO(b"content"))
