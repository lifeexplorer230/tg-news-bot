#!/usr/bin/env python3
"""
Скрипт для запуска HTTP сервера с health check endpoints

Использование:
    python scripts/run_healthcheck_server.py [--port 8080] [--profile marketplace]
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.examples import run_health_check_server
from utils.config import load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


def parse_args():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="Health Check HTTP Server для мониторинга"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Порт для HTTP сервера (по умолчанию: 8080)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host для HTTP сервера (по умолчанию: 0.0.0.0)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        help="Профиль конфигурации (например, marketplace, ai)",
    )
    return parser.parse_args()


async def main():
    """Точка входа"""
    args = parse_args()

    # Загружаем конфигурацию
    config = load_config(profile=args.profile)

    # Настраиваем логирование
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    logger.info("=" * 80)
    logger.info("HEALTH CHECK HTTP SERVER")
    logger.info("=" * 80)
    logger.info(f"Profile: {config.profile}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Host: {args.host}")
    logger.info("=" * 80)

    try:
        # Запускаем сервер (модифицированная версия с host параметром)
        from aiohttp import web

        from monitoring.healthcheck import HealthChecker
        from monitoring.metrics import get_metrics_collector

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

        async def ping_handler(request):
            """Handler для /ping endpoint (простая проверка живости)"""
            return web.json_response({"status": "ok", "message": "pong"})

        # Создаем приложение
        app = web.Application()
        app.router.add_get("/health", health_handler)
        app.router.add_get("/metrics", metrics_handler)
        app.router.add_get("/summary", summary_handler)
        app.router.add_get("/ping", ping_handler)

        # Запускаем сервер
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, args.host, args.port)
        await site.start()

        logger.info("=" * 80)
        logger.info("Health Check Server started successfully")
        logger.info("=" * 80)
        logger.info(f"Endpoints:")
        logger.info(f"  - Ping:        http://localhost:{args.port}/ping")
        logger.info(f"  - Health:      http://localhost:{args.port}/health")
        logger.info(f"  - Metrics:     http://localhost:{args.port}/metrics")
        logger.info(f"  - Summary:     http://localhost:{args.port}/summary")
        logger.info("=" * 80)
        logger.info("Press Ctrl+C to stop")

        # Держим сервер запущенным
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, stopping...")
        finally:
            await runner.cleanup()
            logger.info("Server stopped")

    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
