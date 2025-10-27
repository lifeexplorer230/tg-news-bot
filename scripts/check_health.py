#!/usr/bin/env python3
"""
Скрипт для быстрой проверки здоровья системы

Выполняет полную проверку всех компонентов и выводит результаты.

Использование:
    python scripts/check_health.py [--profile marketplace] [--json]

Exit codes:
    0 - healthy (все компоненты работают)
    1 - degraded (есть предупреждения)
    2 - unhealthy (есть критичные проблемы)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Добавляем корневую директорию в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.healthcheck import HealthChecker
from utils.config import load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


def parse_args():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="Проверка здоровья системы"
    )
    parser.add_argument(
        "--profile",
        type=str,
        help="Профиль конфигурации (например, marketplace, ai)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результаты в JSON формате",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Тихий режим (только exit code)",
    )
    return parser.parse_args()


async def main():
    """Точка входа"""
    args = parse_args()

    # Загружаем конфигурацию
    config = load_config(profile=args.profile)

    # Настраиваем логирование (если не quiet mode)
    if not args.quiet:
        configure_logging(
            level=config.log_level,
            log_file=config.log_file,
            rotation=config.log_rotation,
            file_format=config.log_format,
            date_format=config.log_date_format,
        )

    # Инициализируем HealthChecker
    checker = HealthChecker(
        db_path=config.db_path,
        gemini_api_key=config.gemini_api_key,
        heartbeat_path=config.get("listener.healthcheck.heartbeat_path"),
        heartbeat_max_age=config.get("listener.healthcheck.max_age_seconds", 180),
    )

    # Выполняем проверку
    health = await checker.check_all()

    # Выводим результаты
    if args.json:
        # JSON формат
        print(json.dumps(health.to_dict(), indent=2))
    elif args.quiet:
        # Тихий режим - ничего не выводим
        pass
    else:
        # Человекочитаемый формат
        print_health_report(health, config.profile)

    # Возвращаем exit code
    exit_codes = {
        "healthy": 0,
        "degraded": 1,
        "unhealthy": 2,
    }
    return exit_codes.get(health.status, 2)


def print_health_report(health, profile: str):
    """
    Вывести отчет о здоровье системы в человекочитаемом формате

    Args:
        health: SystemHealth объект
        profile: Имя профиля
    """
    # Emoji для статусов
    status_emoji = {
        "healthy": "✅",
        "degraded": "⚠️",
        "unhealthy": "❌",
    }

    overall_emoji = status_emoji.get(health.status, "❓")

    print("\n" + "=" * 80)
    print(f"{overall_emoji} SYSTEM HEALTH CHECK - {health.status.upper()}")
    print("=" * 80)
    print(f"Profile:   {profile}")
    print(f"Timestamp: {health.timestamp}")
    print("=" * 80)

    # Компоненты
    for component in health.components:
        emoji = status_emoji.get(component.status, "❓")

        print(f"\n{emoji} {component.component.upper()}")
        print(f"  Status:  {component.status}")
        print(f"  Message: {component.message}")

        if component.latency_ms is not None:
            print(f"  Latency: {component.latency_ms:.2f}ms")

        if component.details:
            print("  Details:")
            for key, value in component.details.items():
                print(f"    - {key}: {value}")

    print("\n" + "=" * 80)

    # Краткая сводка
    status_counts = {}
    for component in health.components:
        status_counts[component.status] = status_counts.get(component.status, 0) + 1

    print("Summary:")
    for status, count in sorted(status_counts.items()):
        emoji = status_emoji.get(status, "❓")
        print(f"  {emoji} {status.capitalize()}: {count}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
