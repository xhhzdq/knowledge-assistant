"""LocalDocumentStorage 单元测试。"""
import io
from pathlib import Path

import pytest

from knowledge_assistant.exceptions import StorageError
from knowledge_assistant.storage.local_storage import LocalDocumentStorage


@pytest.fixture
def storage(tmp_path):
    """创建临时存储目录。"""
    return LocalDocumentStorage(upload_dir=tmp_path, max_file_size=1024)


def test_save_returns_stored_object(storage):
    """测试保存文件返回正确的对象信息。"""
    content = b"test content"
    source = io.BytesIO(content)

    result = storage.save("test.txt", source)

    assert result.object_key.startswith("documents/")
    assert result.object_key.endswith(".txt")
    assert result.file_size == len(content)


def test_save_creates_file(storage):
    """测试保存文件后文件确实存在。"""
    content = b"test content"
    source = io.BytesIO(content)

    result = storage.save("test.pdf", source)

    file_path = storage.upload_dir / result.object_key
    assert file_path.exists()
    assert file_path.read_bytes() == content


def test_read_returns_exact_saved_bytes(storage):
    content = b"binary\x00content\xff"
    result = storage.save("binary.bin", io.BytesIO(content))

    assert storage.read(result.object_key) == content


def test_read_missing_object_raises_storage_error(storage):
    with pytest.raises(StorageError, match="Local object not found"):
        storage.read("documents/missing.txt")


@pytest.mark.parametrize("object_key", ["../outside.txt", "documents/../../outside.txt"])
def test_read_rejects_path_outside_upload_directory(storage, object_key):
    with pytest.raises(StorageError, match="outside the uploads"):
        storage.read(object_key)


def test_read_filesystem_failure_is_converted_to_storage_error(storage, monkeypatch):
    result = storage.save("guide.txt", io.BytesIO(b"content"))

    def fail_read(_path: Path) -> bytes:
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "read_bytes", fail_read)

    with pytest.raises(StorageError, match="Unable to read local object"):
        storage.read(result.object_key)


def test_save_exceeds_max_size(storage):
    """测试文件大小超过限制时抛出异常。"""
    large_content = b"x" * 2048  # 超过 1024 字节限制
    source = io.BytesIO(large_content)

    with pytest.raises(ValueError, match="exceeds limit"):
        storage.save("large.bin", source)

    # 验证没有残留文件
    files = list(storage.upload_dir.glob("documents/*"))
    assert len(files) == 0


def test_delete_removes_file(storage):
    """测试删除文件。"""
    content = b"test content"
    source = io.BytesIO(content)
    result = storage.save("test.txt", source)

    storage.delete(result.object_key)

    assert not storage.exists(result.object_key)


def test_delete_idempotent(storage):
    """测试删除不存在的文件不报错（幂等）。"""
    storage.delete("nonexistent.txt")  # 不应抛出异常


@pytest.mark.parametrize("object_key", ["../outside.txt", "documents/../../outside.txt"])
def test_delete_rejects_path_outside_upload_directory(storage, object_key):
    """对象 Key 不能通过路径穿越删除上传目录外的文件。"""
    with pytest.raises(StorageError, match="outside the uploads"):
        storage.delete(object_key)


def test_exists_returns_true_for_saved_file(storage):
    """测试存在检查对已保存文件返回 True。"""
    content = b"test"
    source = io.BytesIO(content)
    result = storage.save("test.txt", source)

    assert storage.exists(result.object_key) is True


def test_exists_returns_false_for_missing_file(storage):
    """测试存在检查对不存在的文件返回 False。"""
    assert storage.exists("nonexistent.txt") is False


def test_generate_unique_keys(storage):
    """测试相同文件名生成不同的对象 Key。"""
    content = b"test"

    result1 = storage.save("test.txt", io.BytesIO(content))
    result2 = storage.save("test.txt", io.BytesIO(content))

    assert result1.object_key != result2.object_key


def test_preserves_extension(storage):
    """测试保留文件扩展名。"""
    content = b"test"
    result = storage.save("document.PDF", io.BytesIO(content))

    assert result.object_key.endswith(".pdf")


def test_handles_no_extension(storage):
    """测试无扩展名时使用 .bin。"""
    content = b"test"
    result = storage.save("noextension", io.BytesIO(content))

    assert result.object_key.endswith(".bin")


def test_upload_dir_created_automatically(storage):
    """测试上传目录自动创建。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        new_dir = Path(tmpdir) / "new" / "uploads"
        LocalDocumentStorage(upload_dir=new_dir)
        assert new_dir.exists()


def test_save_empty_file(storage):
    """测试保存空文件。"""
    content = b""
    source = io.BytesIO(content)

    result = storage.save("empty.txt", source)

    assert result.file_size == 0
    file_path = storage.upload_dir / result.object_key
    assert file_path.exists()
    assert file_path.read_bytes() == b""
    assert storage.read(result.object_key) == b""


def test_save_large_file_within_limit(storage):
    """测试保存接近限制的大文件。"""
    # 1020 字节，小于 1024 限制
    content = b"x" * 1020
    source = io.BytesIO(content)

    result = storage.save("large.txt", source)

    assert result.file_size == 1020
    file_path = storage.upload_dir / result.object_key
    assert file_path.read_bytes() == content


def test_object_key_format(storage):
    """测试对象 Key 格式正确。"""
    content = b"test"
    result = storage.save("test.txt", io.BytesIO(content))

    # 格式应该是 documents/{32位hex}.txt
    parts = result.object_key.split("/")
    assert len(parts) == 2
    assert parts[0] == "documents"
    assert len(parts[1]) == 36  # 32位hex + 4位扩展名(.txt)


def test_save_with_special_characters_in_filename(storage):
    """测试处理包含特殊字符的文件名。"""
    content = b"test"
    # 虽然实际使用中应该先清理文件名，但这里测试基本功能
    result = storage.save("test document (1).txt", io.BytesIO(content))

    assert result.object_key.startswith("documents/")
    assert result.object_key.endswith(".txt")
    assert storage.exists(result.object_key)
