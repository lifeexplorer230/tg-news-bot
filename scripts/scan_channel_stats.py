#!/usr/bin/env python3
"""
Сбор статистики каналов: подписчики, средние просмотры, описание, контакты.

Запускает один раз обход всех активных каналов профиля.
Задержка = 86400 / N_каналов (равномерно за 24 часа).
Запускать раз в неделю через cron. Поддерживает resume: уже просканированные
в этом запуске каналы пропускаются.

Использование:
    sudo bash -c "cd /root/tg-news-bot && source venv/bin/activate && \
        python scripts/scan_channel_stats.py --profile ai"
    sudo bash -c "cd /root/tg-news-bot && source venv/bin/activate && \
        python scripts/scan_channel_stats.py --profile marketplace"
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.functions.channels import GetFullChannelRequest

from database.db import Database
from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from utils.telegram_helpers import safe_connect

logger = setup_logger(__name__)


def extract_contacts(text: str) -> str:
    """Извлечь @username, URL и email из текста описания."""
    if not text:
        return ""
    found = set()
    found.update(re.findall(r"@[\w]{3,}", text))
    found.update(re.findall(r"https?://[^\s]+", text))
    found.update(re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text))
    return ", ".join(sorted(found))


async def ensure_connected(client: TelegramClient, session_name: str) -> None:
    """Переподключить клиент если он отвалился."""
    if not client.is_connected():
        logger.info("  🔄 Переподключение к Telegram...")
        await safe_connect(client, session_name)


async def scan_channel(
    client: TelegramClient,
    session_name: str,
    db: Database,
    channel: dict,
    delay: float,
) -> bool:
    """
    Сканировать один канал, сохранить статистику.
    Возвращает True если обработан (успешно или пропущен), False если нужен повтор.
    """
    username = channel["username"]
    channel_id = channel["id"]

    try:
        await ensure_connected(client, session_name)

        entity = await client.get_entity(username)
        full = await client(GetFullChannelRequest(entity))
        fc = full.full_chat

        participants = getattr(fc, "participants_count", 0) or 0
        about = getattr(fc, "about", "") or ""
        contacts = extract_contacts(about)

        # avg_views: среднее по последним 20 постам
        views_list = [
            msg.views
            async for msg in client.iter_messages(entity, limit=20)
            if msg.views
        ]
        avg_views = int(sum(views_list) / len(views_list)) if views_list else 0

        db.update_channel_stats(channel_id, participants, avg_views, about, contacts)
        logger.info(
            "  ✅ @%-30s  %7d подп.  avg %5d просм.%s",
            username,
            participants,
            avg_views,
            f"  📬 {contacts}" if contacts else "",
        )
        await asyncio.sleep(delay)
        return True

    except FloodWaitError as e:
        wait = e.seconds + 5
        logger.warning("  ⏳ FloodWait %ds для @%s — жду %ds...", e.seconds, username, wait)
        await asyncio.sleep(wait)
        return False  # повторить этот канал

    except (ChannelPrivateError, ChatAdminRequiredError) as e:
        logger.debug("  ⚠️  @%s недоступен: %s", username, e)
        await asyncio.sleep(min(delay, 10))
        return True  # пропустить

    except Exception as e:
        err = str(e)
        if "disconnected" in err.lower():
            # Не пропускаем — переподключимся и повторим
            logger.warning("  🔌 @%s: соединение разорвано, переподключение...", username)
            try:
                await safe_connect(client, session_name)
            except Exception as ce:
                logger.error("  Переподключение не удалось: %s", ce)
                await asyncio.sleep(10)
            return False  # повторить
        logger.warning("  ❌ @%s: %s", username, e)
        await asyncio.sleep(min(delay, 10))
        return True  # пропустить


def get_already_scanned_today(db: Database) -> set[int]:
    """ID каналов с записью в channel_stats за последние 25 часов."""
    cutoff = datetime.utcnow() - timedelta(hours=25)
    with db._pool.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT channel_id FROM channel_stats WHERE scanned_at >= ?",
            (cutoff,),
        ).fetchall()
    return {row[0] for row in rows}


async def main(profile: str):
    config = load_config(profile=profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    db = Database(config.db_path, **config.database_settings())
    all_channels = db.get_active_channels()
    total = len(all_channels)

    if total == 0:
        logger.error("Нет активных каналов в профиле %s", profile)
        sys.exit(1)

    # Пропустить уже просканированные (для resume после сбоя)
    already_done = get_already_scanned_today(db)
    channels = [ch for ch in all_channels if ch["id"] not in already_done]
    skipped_resume = total - len(channels)

    delay = 86400.0 / total
    logger.info("=" * 72)
    logger.info("📡 СКАНЕР СТАТИСТИКИ КАНАЛОВ — профиль: %s", profile)
    logger.info(
        "   Всего: %d  |  К сканированию: %d  |  Уже готово: %d",
        total, len(channels), skipped_resume,
    )
    logger.info("   Задержка: %.1f с (%.1f мин)  |  Итого: ~24 ч", delay, delay / 60)
    logger.info("=" * 72)

    if not channels:
        logger.info("✅ Все каналы уже просканированы сегодня.")
        db.close()
        return

    # Используем processor-сессию, чтобы не конфликтовать с listener
    base_session = config.get("telegram.session_name", "")
    if base_session.endswith("/session"):
        session_name = base_session[:-8] + "/processor"
    elif base_session.endswith("/session.session"):
        session_name = base_session[:-16] + "/processor"
    else:
        session_name = base_session + "_processor"

    client = TelegramClient(
        session_name,
        config.telegram_api_id,
        config.telegram_api_hash,
    )

    try:
        await safe_connect(client, session_name)

        scanned = 0
        with_contacts = 0
        remaining = list(channels)

        while remaining:
            channel = remaining[0]
            idx = skipped_resume + (len(channels) - len(remaining)) + 1
            logger.info("[%d/%d] @%s", idx, total, channel["username"])

            done = await scan_channel(client, session_name, db, channel, delay)
            if done:
                remaining.pop(0)
                scanned += 1
                try:
                    with db._pool.get_connection() as conn:
                        row = conn.execute(
                            "SELECT contact_info FROM channel_stats "
                            "WHERE channel_id=? ORDER BY scanned_at DESC LIMIT 1",
                            (channel["id"],),
                        ).fetchone()
                    if row and row[0]:
                        with_contacts += 1
                except Exception:
                    pass
            # else: разрыв/FloodWait — повторим тот же канал

        logger.info("=" * 72)
        logger.info("✅ Сканирование завершено: %d новых + %d из кэша", scanned, skipped_resume)
        logger.info("📬 Каналов с контактами для рекламы: %d", with_contacts)

        # Топ-10 по подписчикам
        try:
            with db._pool.get_connection() as conn:
                rows = conn.execute(
                    """SELECT c.username, cs.participants_count, cs.avg_message_views
                       FROM channel_stats cs
                       JOIN channels c ON cs.channel_id = c.id
                       WHERE cs.id IN (
                           SELECT MAX(id) FROM channel_stats GROUP BY channel_id
                       )
                       ORDER BY cs.participants_count DESC LIMIT 10"""
                ).fetchall()
            logger.info("=" * 72)
            logger.info("📊 ТОП-10 по подписчикам:")
            for i, (uname, subs, avg) in enumerate(rows, 1):
                logger.info("  %2d. @%-30s  %7d подп.  avg %5d просм.", i, uname, subs, avg)
        except Exception as e:
            logger.warning("Не удалось получить топ: %s", e)

    finally:
        await client.disconnect()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сканер статистики Telegram-каналов")
    parser.add_argument("--profile", required=True, choices=["ai", "marketplace"])
    args = parser.parse_args()
    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
