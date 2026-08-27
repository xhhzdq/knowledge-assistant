"""Alembic 迁移链的 PostgreSQL 集成测试。"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from knowledge_assistant.core.config import DatabaseSettings

FIRST_REVISION = "20260813_01"
HEAD_REVISION = "20260813_02"


@pytest.fixture(scope="module")
def migration_environment(
    monkeypatch_module: pytest.MonkeyPatch,
) -> Iterator[tuple[Config, Engine]]:
    """将 Alembic 安全地指向独立测试库并在结束后清空结构。"""
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
    """提供模块生命周期的环境变量覆盖。"""
    monkeypatch = pytest.MonkeyPatch()
    yield monkeypatch
    monkeypatch.undo()


def test_first_revision_creates_initial_documents_table(
    migration_environment: tuple[Config, Engine],
) -> None:
    """第一条迁移应创建第一版表，但不包含 updated_at。"""
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
    """升级到 head 后应出现 updated_at。"""
    config, engine = migration_environment

    command.upgrade(config, "head")

    columns = inspect(engine).get_columns("documents")
    updated_at = next(column for column in columns if column["name"] == "updated_at")
    assert updated_at["nullable"] is False
    assert updated_at["default"] is not None


def test_second_revision_can_downgrade_and_upgrade_again(
    migration_environment: tuple[Config, Engine],
) -> None:
    """第二条迁移应可回退，并能再次升级到最新状态。"""
    config, engine = migration_environment

    command.downgrade(config, "-1")
    assert "updated_at" not in {
        column["name"] for column in inspect(engine).get_columns("documents")
    }

    command.upgrade(config, "head")
    assert "updated_at" in {
        column["name"] for column in inspect(engine).get_columns("documents")
    }
