#!/usr/bin/env python3
"""
Marketplace News Bot - автоматический агрегатор новостей про маркетплейсы
Поддерживает Ozon и Wildberries
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import threading
import time

import schedule

from database.db import Database
from services.marketplace_processor import MarketplaceProcessor
from services.status_reporter import run_status_reporter
from services.telegram_listener import TelegramListener
from utils.config import Config, load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

# Глобальная переменная для graceful shutdown
running = True
_shutdown_events: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Marketplace News Bot")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["listener", "processor", "all"],
        default="all",
        help="Режим работы бота",
    )
    parser.add_argument(
        "--profile",
        dest="profile",
        help="Имя профиля конфигурации (например, marketplace или ai)",
    )
    return parser.parse_args(argv)


def register_shutdown_event(
    event: asyncio.Event,
) -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
    """Регистрирует asyncio.Event, который будет установлен при остановке."""
    loop = asyncio.get_running_loop()
    entry = (loop, event)
    _shutdown_events.append(entry)
    return entry


def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global running
    if not running:
        return
    running = False
    logger.info("Получен сигнал завершения (%s)...", signal.Signals(sig).name)
    for loop, event in list(_shutdown_events):
        loop.call_soon_threadsafe(event.set)
    _shutdown_events.clear()


async def run_listener_mode(config: Config | None = None):
    """Запуск listener (слушает каналы 24/7)"""
    external_config = config is not None
    config = config or load_config()
    if not external_config:
        configure_logging(
            level=config.log_level,
            log_file=config.log_file,
            rotation=config.log_rotation,
            file_format=config.log_format,
            date_format=config.log_date_format,
        )
        logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    logger.info("=" * 80)
    logger.info("🎧 ЗАПУСК LISTENER - Marketplace News Bot")
    logger.info("=" * 80)

    # Инициализация БД
    db = Database(config.db_path, **config.database_settings())

    listener = TelegramListener(config, db)
    shutdown_event = asyncio.Event()
    token = register_shutdown_event(shutdown_event)

    listener_task = asyncio.create_task(listener.start())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    try:
        done, _ = await asyncio.wait(
            {listener_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_task in done:
            logger.info("Остановка listener по сигналу")
            await listener.stop()
            if not listener_task.done():
                listener_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listener_task
        else:
            shutdown_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_task
    finally:
        if token in _shutdown_events:
            _shutdown_events.remove(token)
        with contextlib.suppress(Exception):
            await listener.stop()
        db.close()


async def run_processor_mode(config: Config | None = None):
    """Запуск processor (обработка новостей)"""
    external_config = config is not None
    config = config or load_config()
    if not external_config:
        configure_logging(
            level=config.log_level,
            log_file=config.log_file,
            rotation=config.log_rotation,
            file_format=config.log_format,
            date_format=config.log_date_format,
        )
        logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    logger.info("=" * 80)
    logger.info("⚙️  ЗАПУСК PROCESSOR - Marketplace News Bot")
    logger.info("=" * 80)

    processor = MarketplaceProcessor(config)
    await processor.run()


def schedule_processor(config):
    """Настроить расписание для processor"""
    schedule_time = config.get("processor.schedule_time", "09:00")
    timezone = config.get("processor.timezone", "Europe/Moscow")

    logger.info(f"⏰ Настройка расписания processor: каждый день в {schedule_time} ({timezone})")

    def run_processor_sync():
        """Синхронная обёртка для запуска processor"""
        logger.info("🔄 Запуск Processor по расписанию...")
        asyncio.run(run_processor_mode())

    schedule.every().day.at(schedule_time).do(run_processor_sync)


def schedule_status_reporter(config, db):
    """Настроить расписание для отправки статуса"""
    if not config.get("status.enabled", False):
        logger.info("📊 Отправка статуса отключена в конфигурации")
        return

    interval_minutes = config.get("status.interval_minutes", 60)
    chat = config.get("status.chat", "Soft Status")

    logger.info(f"📊 Настройка отправки статуса: каждые {interval_minutes} минут в '{chat}'")

    def run_status_sync():
        """Синхронная обёртка для отправки статуса"""
        logger.info("📊 Отправка статуса по расписанию...")
        asyncio.run(run_status_reporter(config, db))

    schedule.every(interval_minutes).minutes.do(run_status_sync)


def run_scheduler():
    """Запустить планировщик задач"""
    global running
    logger.info("📅 Scheduler запущен")

    while running:
        schedule.run_pending()
        time.sleep(60)  # Проверяем каждую минуту


async def start_listener_with_scheduler(config, db):
    """Запустить listener с активным scheduler в фоне"""
    listener = TelegramListener(config, db)
    shutdown_event = asyncio.Event()
    token = register_shutdown_event(shutdown_event)

    listener_task = asyncio.create_task(listener.start())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    try:
        done, _ = await asyncio.wait(
            {listener_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_task in done:
            logger.info("Остановка listener (режим all) по сигналу")
            await listener.stop()
            if not listener_task.done():
                listener_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listener_task
        else:
            shutdown_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_task
    finally:
        if token in _shutdown_events:
            _shutdown_events.remove(token)
        with contextlib.suppress(Exception):
            await listener.stop()


def main():
    """Точка входа"""
    global running

    # Обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    args = parse_args(sys.argv[1:])
    mode = args.mode

    if args.profile:
        os.environ["PROFILE"] = args.profile

    # Загружаем конфигурацию
    config = load_config(profile=args.profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    logger.info("=" * 80)
    logger.info("🚀 MARKETPLACE NEWS BOT")
    logger.info("=" * 80)
    db = Database(config.db_path, **config.database_settings())

    try:
        if mode == "listener":
            # Только listener
            logger.info("Режим: LISTENER")
            asyncio.run(run_listener_mode(config))

        elif mode == "processor":
            # Только processor (одноразовый запуск)
            logger.info("Режим: PROCESSOR (одноразовый запуск)")
            asyncio.run(run_processor_mode(config))

        elif mode == "all":
            # Оба режима: listener + scheduler для processor + status reporter
            logger.info("Режим: ALL (listener + scheduled processor + status reporter)")

            # Настраиваем расписание
            schedule_processor(config)
            schedule_status_reporter(config, db)

            # Запускаем scheduler в отдельном потоке
            scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
            scheduler_thread.start()

            # Запускаем listener (блокирующая операция)
            asyncio.run(start_listener_with_scheduler(config, db))

    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
        running = False
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    main()
