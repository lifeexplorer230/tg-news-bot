#!/usr/bin/env python3
"""
Точка входа для Reels Generator модуля

Используется для запуска в режиме standalone (опционально).
Основной запуск через main.py корневого проекта ТНБ.
"""

import asyncio
import logging

from utils.config import load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def main():
    """Основная функция для standalone запуска"""
    # Загрузить конфигурацию
    config = load_config("reels")

    # Настроить логирование
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
    )

    logger.info("=" * 80)
    logger.info("🎬 REELS GENERATOR - Standalone Mode")
    logger.info("=" * 80)

    # Импортировать процессор
    from reels.services.reels_processor import ReelsProcessor

    # Создать процессор
    processor = ReelsProcessor(config)

    # Обработать новости
    limit = config.get("reels_processor.news_limit", 10)
    logger.info(f"Обработка последних {limit} новостей...")

    enriched_news, scenarios = await processor.process_latest_news(limit)

    logger.info(f"✅ Обработано: {len(scenarios)} сценариев")

    # Отправить на модерацию
    if scenarios:
        await processor.send_to_moderation(scenarios)
        logger.info("✅ Сценарии отправлены на модерацию")
    else:
        logger.warning("⚠️ Нет сценариев для отправки")


if __name__ == "__main__":
    asyncio.run(main())
