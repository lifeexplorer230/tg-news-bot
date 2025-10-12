"""Настройка логирования для бота."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import colorlog

_configured = False
_console_handler: logging.Handler | None = None
_file_handler: logging.Handler | None = None
_rotation_config: dict[str, Any] = {}


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    rotation: dict[str, Any] | None = None,
    file_format: str | None = None,
    date_format: str | None = None,
) -> None:
    """Глобальная настройка логирования (можно вызывать многократно)."""

    global _configured, _console_handler, _file_handler, _rotation_config

    if rotation is not None:
        _rotation_config = rotation or {}

    level_value = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level_value)

    if not _configured:
        console_format = (
            "%(log_color)s%(asctime)s - %(name)s - %(levelname)s%(reset)s - %(message)s"
        )
        console_date = "%Y-%m-%d %H:%M:%S"

        _console_handler = colorlog.StreamHandler(sys.stdout)
        _console_handler.setFormatter(
            colorlog.ColoredFormatter(
                console_format,
                datefmt=console_date,
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "red,bg_white",
                },
            )
        )
        root_logger.addHandler(_console_handler)
        _configured = True

    if log_file:
        resolved_path = str(Path(log_file).resolve())
        if _file_handler and getattr(_file_handler, "baseFilename", None) != resolved_path:
            root_logger.removeHandler(_file_handler)
            _file_handler.close()
            _file_handler = None

        if _file_handler is None:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

            rotate_settings = _rotation_config or {}
            rotation_enabled = rotate_settings.get("enabled", True)
            backup_count = int(rotate_settings.get("backup_count", 5))
            file_datefmt = date_format or "%Y-%m-%d %H:%M:%S"
            file_fmt = file_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

            if rotation_enabled:
                when = rotate_settings.get("when")
                if when:
                    interval = int(rotate_settings.get("interval", 1))
                    handler: logging.Handler = TimedRotatingFileHandler(
                        resolved_path,
                        when=when,
                        interval=interval,
                        backupCount=backup_count,
                        encoding="utf-8",
                    )
                else:
                    max_bytes = int(rotate_settings.get("max_bytes", 10 * 1024 * 1024))
                    handler = RotatingFileHandler(
                        resolved_path,
                        maxBytes=max_bytes,
                        backupCount=backup_count,
                        encoding="utf-8",
                    )
            else:
                handler = logging.FileHandler(resolved_path, encoding="utf-8")

            handler.setFormatter(logging.Formatter(file_fmt, datefmt=file_datefmt))
            root_logger.addHandler(handler)
            _file_handler = handler


def setup_logger(
    name: str,
    log_file: str | None = None,
    level: str = "INFO",
    rotation: dict[str, Any] | None = None,
    file_format: str | None = None,
    date_format: str | None = None,
) -> logging.Logger:
    """Возвращает логгер с гарантированно настроенной глобальной конфигурацией."""

    configure_logging(
        level=level,
        log_file=log_file,
        rotation=rotation,
        file_format=file_format,
        date_format=date_format,
    )
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


# Алиас для совместимости
get_logger = setup_logger
