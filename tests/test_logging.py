"""日志配置测试。"""

import logging
from pathlib import Path

from pytest import CaptureFixture

from knowledge_assistant.core.logging import configure_logging


def test_configure_logging_writes_console_and_file(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """INFO 日志应同时写入控制台和 UTF-8 日志文件。"""
    log_file = tmp_path / "logs" / "app.log"
    configure_logging(log_file)

    logger = logging.getLogger("knowledge_assistant.test")
    logger.info("中文日志测试")

    # 写文件的 Handler 带缓冲区，断言前主动刷新以保证测试结果稳定。
    for handler in logging.getLogger().handlers:
        handler.flush()

    captured = capsys.readouterr()
    assert "中文日志测试" in captured.err
    assert "INFO" in captured.err
    assert "knowledge_assistant.test" in captured.err
    assert "中文日志测试" in log_file.read_text(encoding="utf-8")


def test_configure_logging_replaces_old_handlers(tmp_path: Path) -> None:
    """重复配置日志时不应累积 Handler，避免一条日志重复输出。"""
    configure_logging(tmp_path / "first.log")
    configure_logging(tmp_path / "second.log")

    assert len(logging.getLogger().handlers) == 2
