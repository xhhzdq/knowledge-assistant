"""文档 API 连接真实 PostgreSQL 测试库的集成测试。"""

from collections.abc import Iterator
from pathlib import Path
from shutil import rmtree

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, text
from sqlalchemy.engine import make_url

from knowledge_assistant.api.dependencies import get_document_service
from knowledge_assistant.api.main import app
from knowledge_assistant.core.config import DatabaseSettings
from knowledge_assistant.db.models import DocumentORM
from knowledge_assistant.db.session import create_session_factory
from knowledge_assistant.exceptions import DocumentNotFoundError
from knowledge_assistant.repositories.sqlalchemy_repository import (
    SqlAlchemyDocumentRepository,
)
from knowledge_assistant.services.document_service import DocumentService
from knowledge_assistant.storage.local_storage import LocalDocumentStorage


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    """提供模块生命周期的环境变量覆盖。"""
    monkeypatch = pytest.MonkeyPatch()
    yield monkeypatch
    monkeypatch.undo()


@pytest.fixture(scope="module")
def database_api_environment(
    monkeypatch_module: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[TestClient, Engine, Path]]:
    """使用 Alembic 准备测试库，并让 API 每个请求使用独立 Session。"""
    settings = DatabaseSettings()
    development_database = make_url(settings.database_url).database
    test_database = make_url(settings.test_database_url).database
    if test_database == development_database or not test_database:
        pytest.fail("TEST_DATABASE_URL 必须指向独立测试数据库")
    if not test_database.endswith("_test"):
        pytest.fail("为避免误删数据，测试数据库名必须以 _test 结尾")

    monkeypatch_module.setenv("DATABASE_URL", settings.test_database_url)
    config = Config("alembic.ini")
    engine = create_engine(settings.test_database_url)
    command.downgrade(config, "base")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(config, "head")

    uploads_dir = tmp_path_factory.mktemp("api-database-uploads")
    session_factory = create_session_factory(engine)

    def override_document_service() -> Iterator[DocumentService]:
        with session_factory() as session:
            repository = SqlAlchemyDocumentRepository(session)
            storage = LocalDocumentStorage(uploads_dir)
            yield DocumentService(repository, storage)

    app.dependency_overrides[get_document_service] = override_document_service

    try:
        with TestClient(app) as client:
            yield client, engine, uploads_dir
    finally:
        app.dependency_overrides.clear()
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database_api_state(
    database_api_environment: tuple[TestClient, Engine, Path],
) -> Iterator[None]:
    """每个测试前后清空测试库记录和临时上传文件。"""
    _, engine, uploads_dir = database_api_environment
    with engine.begin() as connection:
        connection.execute(delete(DocumentORM))
    for uploaded_file in uploads_dir.iterdir():
        if uploaded_file.is_dir():
            rmtree(uploaded_file)
        else:
            uploaded_file.unlink()

    yield

    with engine.begin() as connection:
        connection.execute(delete(DocumentORM))
    for uploaded_file in uploads_dir.iterdir():
        if uploaded_file.is_dir():
            rmtree(uploaded_file)
        else:
            uploaded_file.unlink()


def test_document_http_lifecycle_uses_postgresql(
    database_api_environment: tuple[TestClient, Engine, Path],
) -> None:
    """上传、列表、详情和删除应经过 PostgreSQL 完成完整生命周期。"""
    client, engine, uploads_dir = database_api_environment
    upload_response = client.post(
        "/api/v1/documents",
        files={"file": ("学习笔记.txt", "你好，PostgreSQL".encode(), "text/plain")},
    )

    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert uploaded["name"] == "学习笔记.txt"
    assert uploaded["file_type"] == ".txt"
    assert uploaded["file_size"] > 0
    assert "original_path" not in uploaded
    assert "stored_path" not in uploaded

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        stored = SqlAlchemyDocumentRepository(session).get_by_id(uploaded["id"])
        stored_file = uploads_dir / stored.stored_path
        assert stored_file.exists()

    list_response = client.get(
        "/api/v1/documents",
        params={"offset": 0, "limit": 10},
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"] == [uploaded]

    detail_response = client.get(f"/api/v1/documents/{uploaded['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json() == uploaded

    delete_response = client.delete(f"/api/v1/documents/{uploaded['id']}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert not stored_file.exists()

    with session_factory() as session:
        with pytest.raises(DocumentNotFoundError):
            SqlAlchemyDocumentRepository(session).get_by_id(uploaded["id"])


def test_upload_rejects_unsupported_file_type(
    database_api_environment: tuple[TestClient, Engine, Path],
) -> None:
    """不允许的扩展名应返回 400，且不保存文件或元数据。"""
    client, engine, uploads_dir = database_api_environment

    response = client.post(
        "/api/v1/documents",
        files={"file": ("danger.exe", b"not executable", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]
    assert list(uploads_dir.iterdir()) == []
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        assert SqlAlchemyDocumentRepository(session).count() == 0


def test_database_api_returns_404_for_missing_document(
    database_api_environment: tuple[TestClient, Engine, Path],
) -> None:
    """数据库中不存在 UUID 时，详情和删除都应返回 404。"""
    client, _, _ = database_api_environment
    missing_id = "9d4ac41e-f47e-4f06-9954-6fcf01d21111"

    assert client.get(f"/api/v1/documents/{missing_id}").status_code == 404
    assert client.delete(f"/api/v1/documents/{missing_id}").status_code == 404


def test_patch_document_updates_name_and_status(
    database_api_environment: tuple[TestClient, Engine, Path],
) -> None:
    """PATCH 可更新文档名称或状态，并对不存在的文档返回 404。"""
    client, _, _ = database_api_environment

    # 先上传一个文档
    upload = client.post(
        "/api/v1/documents",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]

    # 更新名称
    response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"name": "updated.txt"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "updated.txt"

    # 更新状态
    response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"status": "ready"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

    # 同时更新名称和状态
    response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"name": "renamed.txt", "status": "failed"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "renamed.txt"
    assert response.json()["status"] == "failed"

    # 不存在的文档 → 404
    missing_id = "9d4ac41e-f47e-4f06-9954-6fcf01d21111"
    response = client.patch(
        f"/api/v1/documents/{missing_id}",
        json={"status": "ready"},
    )
    assert response.status_code == 404

    # 空名称在进入路由前就被 Pydantic 的 min_length=1 拦截，因此返回 422。
    response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"name": ""},
    )
    assert response.status_code == 422

    # 无效状态 → 400
    response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"status": "invalid"},
    )
    assert response.status_code == 422
