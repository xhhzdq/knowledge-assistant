"""应用日志配置。"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(log_file: Path, level: int = logging.INFO) -> None:
    """配置控制台日志和按文件大小轮转的文件日志。"""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 控制台日志便于开发和命令行演示，默认写入标准错误流。
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # 单个日志文件最多约 1 MB，最多保留 3 个历史文件。
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # CLI 是程序入口，强制替换旧配置可避免重复初始化导致一条日志输出多次。
    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler],
        force=True,
    )
