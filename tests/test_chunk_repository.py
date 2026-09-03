"""PostgreSQL integration tests for the document Chunk repository."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from knowledge_assistant.core.config import DatabaseSettings
from knowledge_assistant.db.base import Base
from knowledge_assistant.db.models import DocumentChunkORM, DocumentORM
from knowledge_assistant.db.session import create_db_engine, create_session_factory
from knowledge_assistant.exceptions import DocumentConflictError, StorageError
from knowledge_assistant.processing.models import TextChunk
from knowledge_assistant.repositories.chunk_repository import (
    SqlAlchemyDocumentChunkRepository,
)


@pytest.fixture(scope="module")
def database_engine() -> Iterator[Engine]:
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
    Base.metadata.drop_all(database_engine)
    Base.metadata.create_all(database_engine)
    session_factory = create_session_factory(database_engine)
    with session_factory() as database_session:
        yield database_session
    Base.metadata.drop_all(database_engine)


def add_document(session: Session) -> str:
    document_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        DocumentORM(
            id=document_id,
            name="fixture.txt",
            original_path="fixture.txt",
            stored_path=f"documents/{document_id}.txt",
            file_type=".txt",
            file_size=128,
            status="processing",
            created_at=now,
            updated_at=now,
            processing_version=1,
        )
    )
    session.commit()
    return str(document_id)


def make_chunk(
    document_id: str,
    chunk_index: int,
    *,
    chunk_id: str | None = None,
    version: int = 1,
    content: str | None = None,
) -> TextChunk:
    text = content or f"chunk {chunk_index} text"
    return TextChunk(
        id=chunk_id or str(uuid4()),
        document_id=document_id,
        processing_version=version,
        chunk_index=chunk_index,
        content=text,
        content_hash=f"{chunk_index + 1:064x}",
        char_start=chunk_index * 20,
        char_end=chunk_index * 20 + len(text),
        page_start=chunk_index + 1,
        page_end=chunk_index + 1,
        source_type="parser",
        ocr_confidence=None,
        token_count=max(1, len(text.split())),
        created_at=datetime.now(UTC),
    )


def test_replace_for_document_and_list_page_use_chunk_index_order(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    chunks = [make_chunk(document_id, 2), make_chunk(document_id, 0), make_chunk(document_id, 1)]

    repository.replace_for_document(document_id, chunks)

    result = repository.list_page(document_id, offset=0, limit=10)
    assert [chunk.chunk_index for chunk in result] == [0, 1, 2]


def test_replace_removes_previous_chunks(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    repository.replace_for_document(
        document_id,
        [make_chunk(document_id, 0), make_chunk(document_id, 1)],
    )
    replacement = [make_chunk(document_id, 0, version=2, content="new version")]

    repository.replace_for_document(document_id, replacement)

    assert repository.list_page(document_id, 0, 10) == replacement
    assert repository.count(document_id) == 1


def test_pagination_and_count_apply_to_current_chunks(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    repository.replace_for_document(
        document_id,
        [make_chunk(document_id, index) for index in range(5)],
    )

    page = repository.list_page(document_id, offset=1, limit=2)

    assert [chunk.chunk_index for chunk in page] == [1, 2]
    assert repository.count(document_id) == 5


def test_page_and_processing_version_filters_apply_to_list_and_count(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    chunks = [make_chunk(document_id, index, version=2) for index in range(3)]
    repository.replace_for_document(document_id, chunks)

    page = repository.list_page(
        document_id,
        offset=0,
        limit=20,
        processing_version=2,
        page_number=2,
    )

    assert page == [chunks[1]]
    assert repository.count(document_id, processing_version=2, page_number=2) == 1
    assert repository.count(document_id, processing_version=1) == 0


def test_get_many_by_ids_rebuilds_input_order_and_skips_missing_rows(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    first = make_chunk(document_id, 0)
    second = make_chunk(document_id, 1)
    repository.replace_for_document(document_id, [first, second])

    result = repository.get_many_by_ids([second.id, str(uuid4()), first.id, second.id])

    assert [chunk.id for chunk in result] == [second.id, first.id, second.id]


def test_delete_by_document_returns_count_and_removes_chunks(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    repository.replace_for_document(
        document_id,
        [make_chunk(document_id, 0), make_chunk(document_id, 1)],
    )

    deleted = repository.delete_by_document(document_id)

    assert deleted == 2
    assert repository.count(document_id) == 0


def test_constraint_failure_rolls_back_and_preserves_previous_chunks(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    original = [make_chunk(document_id, 0, content="original chunk")]
    repository.replace_for_document(document_id, original)
    duplicate_indexes = [make_chunk(document_id, 0), make_chunk(document_id, 0)]

    with pytest.raises(DocumentConflictError):
        repository.replace_for_document(document_id, duplicate_indexes)

    assert repository.list_page(document_id, 0, 10) == original


def test_deleting_document_cascades_to_chunks(session: Session) -> None:
    document_id = add_document(session)
    repository = SqlAlchemyDocumentChunkRepository(session)
    repository.replace_for_document(document_id, [make_chunk(document_id, 0)])
    session.expire_all()
    document = session.get(DocumentORM, UUID(document_id))
    assert document is not None

    session.delete(document)
    session.commit()

    remaining = session.scalar(
        select(func.count()).select_from(DocumentChunkORM).where(
            DocumentChunkORM.document_id == UUID(document_id)
        )
    )
    assert remaining == 0


def test_invalid_uuid_is_converted_to_storage_error(session: Session) -> None:
    repository = SqlAlchemyDocumentChunkRepository(session)

    with pytest.raises(StorageError, match="Invalid document_id"):
        repository.count("not-a-uuid")
