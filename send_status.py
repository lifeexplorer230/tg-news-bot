#!/usr/bin/env python3
"""
Отправка статуса работы бота в группу
"""
import argparse
import asyncio
import sys

from core.container import get_container, set_container, ServiceContainer
from database.db import Database
from services.status_reporter import run_status_reporter
from utils.config import load_config
from utils.logger import configure_logging, get_logger


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Отправка статуса бота")
    parser.add_argument(
        "--profile",
        dest="profile",
        required=True,
        help="Имя профиля конфигурации (например, marketplace или ai)",
    )
    return parser.parse_args(argv)


async def main():
    # Парсим аргументы
    args = parse_args(sys.argv[1:])

    # Загружаем конфигурацию
    config = load_config(args.profile)

    # Настраиваем логирование
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )
    logger = get_logger(__name__)

    logger.info(f"Отправка статуса для профиля: {config.profile}")

    try:
        # Инициализируем БД
        db = Database(config.db_path)

        # Создаём контейнер с config
        container = ServiceContainer(config=config)
        set_container(container)

        # Отправляем статус
        await run_status_reporter(config, db)

        logger.info("Статус успешно отправлен")
        db.close()

    except Exception as e:
        logger.error(f"Ошибка при отправке статуса: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
