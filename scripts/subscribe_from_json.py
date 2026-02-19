#!/usr/bin/env python3
"""
Подписка на каналы из validated_{profile}.json.
При FloodWait автоматически ждёт и продолжает.
JSON обновляется после каждой успешной подписки.

Использование: python scripts/subscribe_from_json.py --profile ai
               python scripts/subscribe_from_json.py --profile marketplace
"""

import argparse
import asyncio
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.functions.channels import JoinChannelRequest

from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from services.channel_discovery import ChannelDiscovery

logger = setup_logger(__name__)

DELAY_MIN = 7
DELAY_MAX = 13


def _save_remaining(json_path: str, remaining: list[dict]):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(remaining, f, ensure_ascii=False, indent=2)


async def main(profile: str):
    config = load_config(profile=profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    json_path = os.path.join("data", f"validated_{profile}.json")
    if not os.path.exists(json_path):
        print(f"Файл {json_path} не найден")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("Список пуст")
        sys.exit(0)

    total = len(candidates)
    logger.info(f"=== Subscribe from JSON для профиля: {profile} ===")
    logger.info(f"Загружено {total} каналов из {json_path}")

    discovery = ChannelDiscovery(config)
    subscribed = []

    try:
        await discovery.start()

        remaining = list(candidates)

        while remaining:
            candidate = remaining[0]
            username = candidate["username"]
            idx = total - len(remaining) + 1

            try:
                logger.info(f"[{idx}/{total}] Подписка @{username}...")
                entity = await discovery.client.get_entity(username)
                await discovery.client(JoinChannelRequest(entity))

                channel_id = discovery.db.add_channel(username, candidate.get("title", ""))
                discovery._save_channel_meta(channel_id, candidate)
                discovery._log_action("subscribe", username)

                subs = candidate.get("subscribers", 0)
                logger.info(f"  ✅ @{username} ({subs} подп.)")
                subscribed.append(candidate)
                remaining.pop(0)

                # Сохраняем остаток после каждой подписки
                _save_remaining(json_path, remaining)

                if remaining:
                    delay = random.uniform(DELAY_MIN, DELAY_MAX)
                    logger.info(f"  Задержка {delay:.0f}с...")
                    await asyncio.sleep(delay)

            except FloodWaitError as e:
                wait = e.seconds + 5
                logger.warning(f"  ⏳ FloodWait {e.seconds}с — жду {wait}с и продолжаю...")
                await asyncio.sleep(wait)
                # Не удаляем из remaining, попробуем снова

            except (ChannelPrivateError, ChatAdminRequiredError) as e:
                logger.warning(f"  ⚠️ @{username}: {e}")
                remaining.pop(0)
                _save_remaining(json_path, remaining)

            except Exception as e:
                logger.error(f"  ❌ @{username}: {e}")
                remaining.pop(0)
                _save_remaining(json_path, remaining)

        logger.info(f"Готово! Подписано {len(subscribed)} из {total}")

    finally:
        await discovery.stop()

    print(f"\n{'='*60}")
    print(f"Профиль: {profile}")
    print(f"Подписано: {len(subscribed)} из {total}")
    print(f"Осталось в очереди: {len(remaining)}")
    print(f"{'='*60}")
    for s in subscribed:
        subs = s.get("subscribers", 0)
        print(f"  @{s['username']:30s}  {subs:>7} подп.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=["marketplace", "ai"])
    args = parser.parse_args()
    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
