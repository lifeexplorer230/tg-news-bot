"""
Примеры интеграции системы мониторинга с существующими сервисами

Показывает:
- Как использовать AlertManager в TelegramListener
- Как собирать метрики в NewsProcessor
- Как запустить health check endpoint
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from telethon import TelegramClient

from monitoring.alerts import AlertLevel, init_alert_manager
from monitoring.healthcheck import HealthChecker
from monitoring.metrics import get_metrics_collector
from utils.logger import setup_logger

logger = setup_logger(__name__)


# ============================================================================
# Пример 1: Интеграция AlertManager в TelegramListener
# ============================================================================


class TelegramListenerWithAlerts:
    """
    Пример интеграции AlertManager в TelegramListener

    Добавьте этот код в services/telegram_listener.py
    """

    def __init__(self, config, client: TelegramClient):
        self.config = config
        self.client = client

        # Инициализируем AlertManager
        alert_chat = config.get("monitoring.alert_chat", "Soft Status")
        alert_enabled = config.get("monitoring.alerts_enabled", True)
        bot_name = config.get("status.bot_name", "News Bot")

        self.alert_manager = init_alert_manager(
            client=client,
            target_chat=alert_chat,
            bot_name=bot_name,
            enabled=alert_enabled,
        )

    async def start(self):
        """Запуск listener с алертами"""
        # Стартуем AlertManager worker
        await self.alert_manager.start()

        # Отправляем INFO алерт о старте
        await self.alert_manager.info(
            title="Listener Started",
            message="Telegram listener successfully started",
            context={
                "profile": self.config.profile,
                "mode": "listener",
            },
        )

        try:
            # Основная логика listener
            await self._listen_loop()

        except Exception as e:
            # Отправляем CRITICAL алерт при критической ошибке
            await self.alert_manager.critical(
                title="Listener Crashed",
                message=f"Listener encountered critical error: {str(e)}",
                context={
                    "error_type": type(e).__name__,
                    "profile": self.config.profile,
                },
            )
            raise

    async def _listen_loop(self):
        """Основной цикл прослушивания"""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                # ... логика обработки сообщений ...
                consecutive_errors = 0  # Сбрасываем счетчик при успехе

            except Exception as e:
                consecutive_errors += 1

                # Отправляем алерт в зависимости от количества ошибок
                if consecutive_errors >= max_consecutive_errors:
                    await self.alert_manager.error(
                        title="Multiple Listener Errors",
                        message=f"Listener encountered {consecutive_errors} consecutive errors",
                        context={
                            "last_error": str(e),
                            "consecutive_errors": consecutive_errors,
                        },
                    )
                elif consecutive_errors >= 3:
                    await self.alert_manager.warning(
                        title="Listener Errors",
                        message=f"Listener encountered {consecutive_errors} errors",
                        context={
                            "last_error": str(e),
                        },
                    )

                await asyncio.sleep(5)

    async def stop(self):
        """Остановка listener с алертами"""
        await self.alert_manager.info(
            title="Listener Stopped",
            message="Telegram listener stopped gracefully",
            context={
                "profile": self.config.profile,
            },
        )

        # Останавливаем AlertManager worker
        await self.alert_manager.stop()


# ============================================================================
# Пример 2: Сбор метрик в NewsProcessor
# ============================================================================


class NewsProcessorWithMetrics:
    """
    Пример интеграции метрик в NewsProcessor

    Добавьте этот код в services/news_processor.py
    """

    def __init__(self, config):
        self.config = config
        self.metrics = get_metrics_collector()

        # Регистрируем метрики
        self.metrics.counter(
            "news_processor_runs_total",
            "Total number of processor runs",
        )
        self.metrics.counter(
            "news_processed_total",
            "Total number of news processed",
        )
        self.metrics.counter(
            "news_published_total",
            "Total number of news published",
        )
        self.metrics.histogram(
            "processor_duration_seconds",
            "Duration of processor run in seconds",
        )

    async def run(self):
        """Запуск processor с метриками"""
        # Увеличиваем счетчик запусков
        self.metrics.inc_counter("news_processor_runs_total")

        # Измеряем время выполнения
        with self.metrics.timer("processor_duration_seconds"):
            try:
                await self._process_news()

            except Exception as e:
                # Увеличиваем счетчик ошибок
                self.metrics.inc_counter(
                    "news_processor_errors_total",
                    labels={"error_type": type(e).__name__},
                )
                raise

    async def _process_news(self):
        """Обработка новостей с метриками"""
        # ... получаем новости из БД ...
        raw_messages = []  # Здесь будут новости из БД

        # Обновляем gauge с количеством необработанных новостей
        self.metrics.set_gauge(
            "news_unprocessed_count",
            len(raw_messages),
        )

        for message in raw_messages:
            # Измеряем время обработки одной новости
            with self.metrics.timer(
                "news_processing_duration_seconds",
                labels={"category": message.get("category", "unknown")},
            ):
                await self._process_single_message(message)

            # Увеличиваем счетчик обработанных новостей
            self.metrics.inc_counter(
                "news_processed_total",
                labels={"category": message.get("category", "unknown")},
            )

    async def _process_single_message(self, message: dict[str, Any]):
        """Обработка одного сообщения"""
        # ... логика обработки ...
        pass

    async def _publish_news(self, news_list: list[dict[str, Any]]):
        """Публикация новостей с метриками"""
        for news in news_list:
            # Измеряем время публикации
            with self.metrics.timer("news_publishing_duration_seconds"):
                # ... логика публикации ...
                pass

            # Увеличиваем счетчик опубликованных новостей
            self.metrics.inc_counter(
                "news_published_total",
                labels={"category": news.get("category", "unknown")},
            )


# ============================================================================
# Пример 3: Health Check endpoint
# ============================================================================


async def run_health_check_server(config, port: int = 8080):
    """
    Простой HTTP сервер для health check endpoint

    Args:
        config: Конфигурация
        port: Порт для сервера
    """
    from aiohttp import web

    # Инициализируем HealthChecker
    checker = HealthChecker(
        db_path=config.db_path,
        gemini_api_key=config.gemini_api_key,
        heartbeat_path=config.get("listener.healthcheck.heartbeat_path"),
        heartbeat_max_age=config.get("listener.healthcheck.max_age_seconds", 180),
    )

    async def health_handler(request):
        """Handler для /health endpoint"""
        health = await checker.check_all()
        return web.json_response(health.to_dict())

    async def metrics_handler(request):
        """Handler для /metrics endpoint (Prometheus)"""
        metrics = get_metrics_collector()
        prometheus_text = metrics.export_prometheus()
        return web.Response(text=prometheus_text, content_type="text/plain")

    async def summary_handler(request):
        """Handler для /summary endpoint (краткая сводка)"""
        metrics = get_metrics_collector()
        summary = metrics.get_summary()
        return web.json_response(summary)

    # Создаем приложение
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/summary", summary_handler)

    # Запускаем сервер
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Health check server started on port {port}")
    logger.info(f"  - Health check: http://localhost:{port}/health")
    logger.info(f"  - Metrics: http://localhost:{port}/metrics")
    logger.info(f"  - Summary: http://localhost:{port}/summary")

    # Держим сервер запущенным
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


# ============================================================================
# Пример 4: Standalone health check скрипт
# ============================================================================


async def standalone_health_check():
    """
    Standalone скрипт для проверки здоровья системы

    Использование:
        python -m monitoring.examples
    """
    from utils.config import load_config

    config = load_config()

    checker = HealthChecker(
        db_path=config.db_path,
        gemini_api_key=config.gemini_api_key,
        heartbeat_path=config.get("listener.healthcheck.heartbeat_path"),
        heartbeat_max_age=config.get("listener.healthcheck.max_age_seconds", 180),
    )

    health = await checker.check_all()

    # Выводим результаты
    print("\n" + "=" * 80)
    print(f"SYSTEM HEALTH CHECK - {health.status.upper()}")
    print("=" * 80)

    for component in health.components:
        status_emoji = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unhealthy": "❌",
        }.get(component.status, "❓")

        print(f"\n{status_emoji} {component.component.upper()}")
        print(f"  Status: {component.status}")
        print(f"  Message: {component.message}")

        if component.latency_ms is not None:
            print(f"  Latency: {component.latency_ms:.2f}ms")

        if component.details:
            print("  Details:")
            for key, value in component.details.items():
                print(f"    - {key}: {value}")

    print("\n" + "=" * 80)

    # Возвращаем exit code на основе статуса
    exit_codes = {
        "healthy": 0,
        "degraded": 1,
        "unhealthy": 2,
    }
    return exit_codes.get(health.status, 2)


if __name__ == "__main__":
    # Запускаем standalone health check
    exit_code = asyncio.run(standalone_health_check())
    exit(exit_code)
