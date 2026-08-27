"""CLI 命令入口的集成测试。"""

from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from knowledge_assistant import cli
from knowledge_assistant.core.config import Settings


def build_test_settings(tmp_path: Path) -> Settings:
    """创建完全位于 pytest 临时目录中的应用配置。"""
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    return Settings(
        project_root=tmp_path,
        data_dir=data_dir,
        uploads_dir=data_dir / "uploads",
        metadata_file=data_dir / "documents.json",
        logs_dir=logs_dir,
        log_file=logs_dir / "app.log",
    )


def use_test_settings(monkeypatch: MonkeyPatch, tmp_path: Path) -> Settings:
    """让 CLI 使用临时配置，避免测试污染项目真实数据。"""
    settings = build_test_settings(tmp_path)
    monkeypatch.setattr(cli.Settings, "default", lambda: settings)
    return settings


def test_cli_help() -> None:
    """CLI 应提供帮助页面并以成功状态退出。"""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0


def test_cli_document_lifecycle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """add、list、show、delete 应通过完整 CLI 调用链协同工作。"""
    settings = use_test_settings(monkeypatch, tmp_path)
    source = tmp_path / "学习资料.txt"
    source.write_text("CLI 集成测试内容", encoding="utf-8")

    assert cli.main(["add", str(source)]) == 0
    add_output = capsys.readouterr().out
    document_id = add_output.removeprefix("Document added: ").strip()

    assert document_id
    assert settings.metadata_file.exists()
    assert len(list(settings.uploads_dir.glob("*学习资料.txt"))) == 1

    assert cli.main(["list"]) == 0
    list_output = capsys.readouterr().out
    assert document_id in list_output
    assert "学习资料.txt" in list_output
    assert "uploaded" in list_output

    assert cli.main(["show", document_id]) == 0
    show_output = capsys.readouterr().out
    assert f"ID: {document_id}" in show_output
    assert "Name: 学习资料.txt" in show_output
    assert "Status: uploaded" in show_output

    assert cli.main(["delete", document_id]) == 0
    delete_output = capsys.readouterr().out
    assert f"Document deleted: {document_id}" in delete_output
    assert list(settings.uploads_dir.glob("*学习资料.txt")) == []

    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out.strip() == "No documents found."


@pytest.mark.parametrize("command", ["show", "delete"])
def test_cli_missing_document_exits_with_error(
    command: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """查询或删除不存在的文档时应输出错误并返回状态码 1。"""
    settings = use_test_settings(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        cli.main([command, "missing-id"])

    assert exc_info.value.code == 1
    assert "Error: Document not found: missing-id" in capsys.readouterr().err
    assert "CLI 命令执行失败" in settings.log_file.read_text(encoding="utf-8")


def test_cli_add_missing_file_exits_with_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """添加不存在的源文件时不应创建元数据或上传副本。"""
    settings = use_test_settings(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["add", str(tmp_path / "missing.txt")])

    assert exc_info.value.code == 1
    assert "Source file does not exist" in capsys.readouterr().err
    assert not settings.metadata_file.exists()
    assert list(settings.uploads_dir.iterdir()) == []
