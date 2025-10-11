#!/usr/bin/env python3
"""
Marketplace News Bot - автоматический агрегатор новостей про маркетплейсы
Поддерживает Ozon и Wildberries
"""
import asyncio
import sys
import signal
import time
import schedule
import threading
from utils.config import load_config
from utils.logger import get_logger
from database.db import Database
from services.telegram_listener import TelegramListener
from services.marketplace_processor import MarketplaceProcessor
from services.status_reporter import run_status_reporter

logger = get_logger(__name__)

# Глобальная переменная для graceful shutdown
running = True


def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global running
    logger.info("Получен сигнал завершения...")
    running = False
    sys.exit(0)


async def run_listener_mode():
    """Запуск listener (слушает каналы 24/7)"""
    config = load_config()

    logger.info("=" * 80)
    logger.info("🎧 ЗАПУСК LISTENER - Marketplace News Bot")
    logger.info("=" * 80)

    # Инициализация БД
    db = Database(config.db_path)

    listener = TelegramListener(config, db)
    await listener.start()


async def run_processor_mode():
    """Запуск processor (обработка новостей)"""
    config = load_config()

    logger.info("=" * 80)
    logger.info("⚙️  ЗАПУСК PROCESSOR - Marketplace News Bot")
    logger.info("=" * 80)

    processor = MarketplaceProcessor(config)
    await processor.run()


def schedule_processor(config, db):
    """Настроить расписание для processor"""
    schedule_time = config.get('processor.schedule_time', '09:00')
    timezone = config.get('processor.timezone', 'Europe/Moscow')

    logger.info(f"⏰ Настройка расписания processor: каждый день в {schedule_time} ({timezone})")

    def run_processor_sync():
        """Синхронная обёртка для запуска processor"""
        logger.info("🔄 Запуск Processor по расписанию...")
        asyncio.run(run_processor_mode())

    schedule.every().day.at(schedule_time).do(run_processor_sync)


def schedule_status_reporter(config, db):
    """Настроить расписание для отправки статуса"""
    if not config.get('status.enabled', False):
        logger.info("📊 Отправка статуса отключена в конфигурации")
        return

    interval_minutes = config.get('status.interval_minutes', 60)
    chat = config.get('status.chat', 'Soft Status')

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
    await listener.start()


def main():
    """Точка входа"""
    global running

    # Обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Проверяем режим запуска
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode not in ["listener", "processor", "all"]:
        print("Usage: python main.py [listener|processor|all]")
        print("")
        print("Modes:")
        print("  listener  - Слушает Telegram каналы и сохраняет сообщения")
        print("  processor - Обрабатывает сообщения, отбирает новости и публикует (одноразово)")
        print("  all       - Listener + scheduled processor + status reporter (по умолчанию)")
        sys.exit(1)

    logger.info("=" * 80)
    logger.info("🚀 MARKETPLACE NEWS BOT")
    logger.info("=" * 80)

    # Загружаем конфигурацию
    config = load_config()
    db = Database(config.db_path)

    try:
        if mode == "listener":
            # Только listener
            logger.info("Режим: LISTENER")
            asyncio.run(run_listener_mode())

        elif mode == "processor":
            # Только processor (одноразовый запуск)
            logger.info("Режим: PROCESSOR (одноразовый запуск)")
            asyncio.run(run_processor_mode())

        elif mode == "all":
            # Оба режима: listener + scheduler для processor + status reporter
            logger.info("Режим: ALL (listener + scheduled processor + status reporter)")

            # Настраиваем расписание
            schedule_processor(config, db)
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
