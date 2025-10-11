"""Настройка логирования для бота"""
import logging
import sys
from pathlib import Path
import colorlog


def setup_logger(name: str, log_file: str = None, level: str = "INFO") -> logging.Logger:
    """
    Настраивает и возвращает logger с цветным выводом в консоль

    Args:
        name: Имя логгера
        log_file: Путь к файлу логов (опционально)
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Настроенный logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Избегаем дублирования handlers
    if logger.handlers:
        return logger

    # Формат логов
    log_format = "%(log_color)s%(asctime)s - %(name)s - %(levelname)s%(reset)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Цветной вывод в консоль
    console_handler = colorlog.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        colorlog.ColoredFormatter(
            log_format,
            datefmt=date_format,
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
    )
    logger.addHandler(console_handler)

    # Вывод в файл (если указан)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt=date_format
            )
        )
        logger.addHandler(file_handler)

    return logger


# Алиас для совместимости
get_logger = setup_logger
