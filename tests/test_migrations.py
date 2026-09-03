"""Alembic migration-chain integration tests against PostgreSQL."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from knowledge_assistant.core.config import DatabaseSettings

FIRST_REVISION = "20260813_01"
SECOND_REVISION = "20260813_02"
HEAD_REVISION = "20260901_01"


@pytest.fixture(scope="module")
def migration_environment(
    monkeypatch_module: pytest.MonkeyPatch,
) -> Iterator[tuple[Config, Engine]]:
    """Point Alembic at an isolated test database and clean it afterwards."""
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

    try:
        yield config, engine
    finally:
        command.downgrade(config, "base")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    monkeypatch = pytest.MonkeyPatch()
    yield monkeypatch
    monkeypatch.undo()


def _insert_document(connection: Connection, document_id: str, stored_path: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO documents (
                id, name, original_path, stored_path, file_type, file_size, status
            ) VALUES (
                :id, 'fixture.txt', 'fixture.txt', :stored_path, '.txt', 12, 'uploaded'
            )
            """
        ),
        {"id": document_id, "stored_path": stored_path},
    )


def _insert_chunk(
    connection: Connection,
    *,
    chunk_id: str,
    document_id: str,
    chunk_index: int = 0,
    char_start: int = 0,
    char_end: int = 12,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO document_chunks (
                id, document_id, processing_version, chunk_index, content,
                content_hash, char_start, char_end, page_start, page_end,
                source_type, ocr_confidence, token_count
            ) VALUES (
                :id, :document_id, 1, :chunk_index, 'fixture text',
                :content_hash, :char_start, :char_end, 1, 1,
                'parser', NULL, 2
            )
            """
        ),
        {
            "id": chunk_id,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "content_hash": "a" * 64,
            "char_start": char_start,
            "char_end": char_end,
        },
    )


def test_first_revision_creates_initial_documents_table(
    migration_environment: tuple[Config, Engine],
) -> None:
    config, engine = migration_environment
    command.upgrade(config, FIRST_REVISION)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {"alembic_version", "documents"}
    assert [column["name"] for column in inspector.get_columns("documents")] == [
        "id",
        "name",
        "original_path",
        "stored_path",
        "file_type",
        "file_size",
        "status",
        "created_at",
    ]


def test_second_revision_adds_updated_at(
    migration_environment: tuple[Config, Engine],
) -> None:
    config, engine = migration_environment
    command.upgrade(config, SECOND_REVISION)

    columns = inspect(engine).get_columns("documents")
    updated_at = next(column for column in columns if column["name"] == "updated_at")
    assert updated_at["nullable"] is False
    assert updated_at["default"] is not None


def test_head_preserves_existing_documents_and_adds_processing_defaults(
    migration_environment: tuple[Config, Engine],
) -> None:
    config, engine = migration_environment
    document_id = str(uuid4())
    with engine.begin() as connection:
        _insert_document(connection, document_id, "fixtures/pre-migration.txt")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT processing_version, content_hash, processed_at, processing_error
                FROM documents WHERE id = :id
                """
            ),
            {"id": document_id},
        ).one()
    assert row == (0, None, None, None)


def test_head_creates_chunk_table_constraints_indexes_and_cascade(
    migration_environment: tuple[Config, Engine],
) -> None:
    _, engine = migration_environment
    inspector = inspect(engine)
    assert {"documents", "document_chunks"}.issubset(inspector.get_table_names())

    foreign_key = inspector.get_foreign_keys("document_chunks")[0]
    assert foreign_key["referred_table"] == "documents"
    assert foreign_key["options"].get("ondelete") == "CASCADE"

    unique_names = {
        constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")
    }
    assert "uq_document_chunks_document_version_index" in unique_names

    check_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("document_chunks")
    }
    assert {
        "ck_document_chunks_processing_version_positive",
        "ck_document_chunks_chunk_index_non_negative",
        "ck_document_chunks_content_not_blank",
        "ck_document_chunks_content_hash_length",
        "ck_document_chunks_char_start_non_negative",
        "ck_document_chunks_char_range",
        "ck_document_chunks_page_range",
        "ck_document_chunks_source_type",
        "ck_document_chunks_ocr_confidence",
        "ck_document_chunks_token_count_positive",
    }.issubset(check_names)

    index_names = {index["name"] for index in inspector.get_indexes("document_chunks")}
    assert {
        "ix_document_chunks_document_chunk",
        "ix_document_chunks_document_version",
    }.issubset(index_names)


def test_chunk_unique_range_constraints_and_cascade_delete(
    migration_environment: tuple[Config, Engine],
) -> None:
    _, engine = migration_environment
    document_id = str(uuid4())
    with engine.begin() as connection:
        _insert_document(connection, document_id, f"fixtures/{document_id}.txt")
        _insert_chunk(connection, chunk_id=str(uuid4()), document_id=document_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            _insert_chunk(connection, chunk_id=str(uuid4()), document_id=document_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            _insert_chunk(
                connection,
                chunk_id=str(uuid4()),
                document_id=document_id,
                chunk_index=1,
                char_start=12,
                char_end=12,
            )

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        remaining = connection.scalar(
            text("SELECT count(*) FROM document_chunks WHERE document_id = :id"),
            {"id": document_id},
        )
    assert remaining == 0


def test_head_revision_can_downgrade_and_upgrade_again(
    migration_environment: tuple[Config, Engine],
) -> None:
    config, engine = migration_environment
    command.downgrade(config, SECOND_REVISION)

    inspector = inspect(engine)
    assert "document_chunks" not in inspector.get_table_names()
    assert "processing_version" not in {
        column["name"] for column in inspector.get_columns("documents")
    }

    command.upgrade(config, "head")
    assert "document_chunks" in inspect(engine).get_table_names()

    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == HEAD_REVISION
