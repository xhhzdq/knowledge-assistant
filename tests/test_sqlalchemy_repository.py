"""PostgreSQL 数据库版文档 Repository 的集成测试。"""

from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from knowledge_assistant.core.config import DatabaseSettings
from knowledge_assistant.db.base import Base
from knowledge_assistant.db.models import DocumentORM  # noqa: F401
from knowledge_assistant.db.session import create_db_engine, create_session_factory
from knowledge_assistant.exceptions import DocumentConflictError, DocumentNotFoundError
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.sqlalchemy_repository import (
    SqlAlchemyDocumentRepository,
)


@pytest.fixture(scope="module")
def database_engine() -> Iterator[Engine]:
    """只允许在名称明确以 _test 结尾的独立测试库中建表。"""
    settings = DatabaseSettings()
    development_database = make_url(settings.database_url).database
    test_database = make_url(settings.test_database_url).database

    if test_database == development_database or not test_database:
        pytest.fail("TEST_DATABASE_URL 必须指向独立测试数据库")
    if not test_database.endswith("_test"):
        pytest.fail("为避免误删数据，测试数据库名必须以 _test 结尾")

    engine = create_db_engine(settings.test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(database_engine: Engine) -> Iterator[Session]:
    """每个测试都从空表开始，避免测试数据相互影响。"""
    Base.metadata.drop_all(database_engine)
    Base.metadata.create_all(database_engine)
    session_factory = create_session_factory(database_engine)

    with session_factory() as database_session:
        yield database_session

    Base.metadata.drop_all(database_engine)


def make_document(*, document_id: str | None = None, stored_path: str | None = None) -> Document:
    """创建字段稳定且 UUID 合法的测试文档。"""
    identifier = document_id or str(uuid4())
    return Document(
        id=identifier,
        name="guide.txt",
        original_path="D:\\examples\\guide.txt",
        stored_path=stored_path or f"D:\\data\\uploads\\{identifier}_guide.txt",
        file_type=".txt",
        file_size=128,
        status="uploaded",
        created_at="2026-08-13T06:00:00+00:00",
    )


def test_add_persists_document_across_sessions(session: Session, database_engine: Engine) -> None:
    """提交后的数据应能被新 Session 查询。"""
    document = make_document()
    SqlAlchemyDocumentRepository(session).add(document)

    session_factory = create_session_factory(database_engine)
    with session_factory() as new_session:
        result = SqlAlchemyDocumentRepository(new_session).get_by_id(document.id)

    assert result == document


def test_list_all_returns_persisted_documents(session: Session) -> None:
    """列表查询应把 ORM 对象转换为领域对象。"""
    repository = SqlAlchemyDocumentRepository(session)
    first = make_document()
    second = make_document()
    repository.add(first)
    repository.add(second)

    assert {document.id for document in repository.list_all()} == {first.id, second.id}


def test_get_by_id_raises_when_document_is_missing(session: Session) -> None:
    """不存在的 UUID 应转换成项目领域异常。"""
    repository = SqlAlchemyDocumentRepository(session)

    with pytest.raises(DocumentNotFoundError, match="Document not found"):
        repository.get_by_id(str(uuid4()))


def test_invalid_uuid_is_treated_as_missing_document(session: Session) -> None:
    """格式错误的 ID 不应泄露数据库驱动异常。"""
    repository = SqlAlchemyDocumentRepository(session)

    with pytest.raises(DocumentNotFoundError, match="Document not found"):
        repository.get_by_id("not-a-uuid")


def test_update_persists_changed_fields(session: Session) -> None:
    """更新应提交并返回更新后的领域对象。"""
    repository = SqlAlchemyDocumentRepository(session)
    original = make_document()
    repository.add(original)
    changed = replace(original, name="updated.txt", file_type=".txt", status="ready")

    result = repository.update(changed)

    assert result == changed
    assert repository.get_by_id(original.id) == changed


def test_update_raises_when_document_is_missing(session: Session) -> None:
    """更新不存在的文档时不应静默插入新记录。"""
    repository = SqlAlchemyDocumentRepository(session)

    with pytest.raises(DocumentNotFoundError, match="Document not found"):
        repository.update(make_document())


def test_delete_removes_and_returns_document(session: Session) -> None:
    """删除应返回删除前的数据并提交事务。"""
    repository = SqlAlchemyDocumentRepository(session)
    document = make_document()
    repository.add(document)

    removed = repository.delete(document.id)

    assert removed == document
    with pytest.raises(DocumentNotFoundError):
        repository.get_by_id(document.id)


def test_delete_raises_when_document_is_missing(session: Session) -> None:
    """删除不存在的文档时应返回统一领域异常。"""
    repository = SqlAlchemyDocumentRepository(session)

    with pytest.raises(DocumentNotFoundError, match="Document not found"):
        repository.delete(str(uuid4()))


def test_duplicate_stored_path_rolls_back_transaction(session: Session) -> None:
    """违反唯一约束后应回滚，使 Session 仍然可以继续使用。"""
    repository = SqlAlchemyDocumentRepository(session)
    stored_path = "D:\\data\\uploads\\same.txt"
    first = make_document(stored_path=stored_path)
    duplicate = make_document(stored_path=stored_path)
    repository.add(first)

    with pytest.raises(DocumentConflictError, match="conflicts with existing data"):
        repository.add(duplicate)

    assert repository.list_all() == [first]
