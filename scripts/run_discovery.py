#!/usr/bin/env python3
"""
Скрипт запуска авторасширения каналов.
Использование: python scripts/run_discovery.py --profile marketplace
Cron: 0 2 * * * cd /root/tg-news-bot && venv/bin/python scripts/run_discovery.py --profile marketplace
      5 2 * * * cd /root/tg-news-bot && venv/bin/python scripts/run_discovery.py --profile ai
(02:00 UTC = 05:00 МСК)
"""

import argparse
import asyncio
import fcntl
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from services.channel_discovery import ChannelDiscovery

logger = setup_logger(__name__)

SERVICE_NAMES = {
    "ai": "tg-news-bot-ai.service",
    "marketplace": "tg-news-bot-marketplace.service",
}


def _systemctl(action: str, service: str) -> bool:
    """Выполнить systemctl action service. Возвращает True при успехе."""
    try:
        result = subprocess.run(
            ["systemctl", action, service],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"systemctl {action} {service} — OK")
            return True
        logger.error(f"systemctl {action} {service} — {result.stderr.strip()}")
        return False
    except Exception as e:
        logger.error(f"systemctl {action} {service} — {e}")
        return False


async def main(profile: str):
    # ── Блокировка от повторного запуска ──────────────────────────
    lock_path = f"/tmp/tg-news-bot-discovery-{profile}.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Discovery для '{profile}' уже запущен. Выход.")
        sys.exit(0)

    try:
        config = load_config(profile=profile)
        configure_logging(
            level=config.log_level,
            log_file=config.log_file,
            rotation=config.log_rotation,
            file_format=config.log_format,
            date_format=config.log_date_format,
        )

        service = SERVICE_NAMES.get(profile, "")

        # ── Останавливаем listener (чтобы не было конфликта сессий) ──
        if service:
            logger.info(f"Останавливаем {service} перед discovery...")
            _systemctl("stop", service)
            await asyncio.sleep(3)  # даём время на корректное завершение

        logger.info(f"Запуск discovery для профиля: {profile}")

        discovery = ChannelDiscovery(config)
        try:
            await discovery.start()
            await discovery.run_full_cycle()

            stats = discovery.get_discovery_stats()
            logger.info(f"Статистика: {stats}")
        except Exception as e:
            logger.error(f"Ошибка discovery: {e}", exc_info=True)
        finally:
            await discovery.stop()

        logger.info("Discovery завершён")

        # ── Запускаем listener (подхватит новые каналы через get_dialogs) ──
        if service:
            logger.info(f"Запускаем {service}...")
            _systemctl("start", service)

    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Channel Discovery")
    parser.add_argument("--profile", required=True, choices=["marketplace", "ai"])
    args = parser.parse_args()

    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
