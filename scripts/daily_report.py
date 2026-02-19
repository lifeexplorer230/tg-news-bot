#!/usr/bin/env python3
"""
Ежедневный отчёт о состоянии каналов.
Отправляет в Telegram через бот-токен.
Cron: 0 6 * * * cd /root/tg-news-bot && python scripts/daily_report.py --profile marketplace
      0 6 * * * cd /root/tg-news-bot && python scripts/daily_report.py --profile ai
(06:00 UTC = 09:00 МСК)
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, UTC

from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from services.channel_discovery import ChannelDiscovery
from database.db import Database

logger = setup_logger(__name__)

# Чат для отчётов (можно переопределить через env)
REPORT_CHAT = os.getenv("DISCOVERY_REPORT_CHAT", "Soft Status")


async def main(profile: str):
    config = load_config(profile=profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    discovery = ChannelDiscovery(config)
    db = Database(config.db_path, **config.database_settings())

    try:
        # Получаем статистику
        disc_stats = discovery.get_discovery_stats()
        db_stats = db.get_stats()
        today = datetime.now(UTC).strftime("%d.%m.%Y")

        # Формируем отчёт
        top_list = ""
        for i, ch in enumerate(disc_stats.get("top_channels", []), 1):
            top_list += f"  {i}. @{ch['username']} — {ch['scoring']}pts, {ch['subscribers']} подп.\n"

        report = f"""📊 Отчёт Discovery [{profile}] за {today}

🔢 Каналы:
  • Всего активных: {db_stats['active_channels']}
  • Найдено через discovery: {disc_stats['total_discovered']}
  • Активных discovery: {disc_stats['active_discovered']}
  • Средний scoring: {disc_stats['avg_scoring']}

📈 Сегодня:
  • Подписок: {disc_stats['subscribed_today']}/{20}
  • Отписок: {disc_stats['unsubscribed_today']}/{5}

🏆 Топ-5 каналов:
{top_list or '  (нет данных)'}

📬 Сообщений в БД: {db_stats['total_messages']}
📰 Опубликовано всего: {db_stats['total_published']}"""

        logger.info(f"Отчёт:\n{report}")

        # Отправляем через Telethon
        from telethon import TelegramClient
        from utils.telegram_helpers import safe_connect

        client = TelegramClient(
            config.get("telegram.session_name"),
            config.telegram_api_id,
            config.telegram_api_hash,
        )
        session_name = config.get("telegram.session_name", "session")
        await safe_connect(client, session_name)

        try:
            await client.send_message(REPORT_CHAT, report)
            logger.info(f"✅ Отчёт отправлен в '{REPORT_CHAT}'")
        finally:
            await client.disconnect()

    except Exception as e:
        logger.error(f"❌ Ошибка отчёта: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

    logger.info("✅ Отчёт завершён")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Discovery Report")
    parser.add_argument("--profile", required=True, choices=["marketplace", "ai"])
    args = parser.parse_args()

    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
