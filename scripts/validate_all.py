#!/usr/bin/env python3
"""
Сбор рекомендаций + валидация ВСЕХ кандидатов через веб.
Сохраняет результат в data/validated_{profile}.json для последующей подписки.

Использование: python scripts/validate_all.py --profile ai
               python scripts/validate_all.py --profile marketplace
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from services.channel_discovery import ChannelDiscovery

logger = setup_logger(__name__)


async def main(profile: str):
    config = load_config(profile=profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    logger.info(f"=== Validate ALL для профиля: {profile} ===")

    discovery = ChannelDiscovery(config)
    try:
        await discovery.start()

        # 1. Сбор рекомендаций
        candidates = await discovery.discover_via_recommendations()
        logger.info(f"Всего кандидатов: {len(candidates)}")

        if not candidates:
            logger.info("Кандидатов нет, выходим")
            return

        # 2. Валидация ВСЕХ (без лимита MAX_CANDIDATES_PER_RUN)
        logger.info(f"Валидация ВСЕХ {len(candidates)} кандидатов через веб...")
        validated = []
        for i, c in enumerate(candidates):
            logger.info(f"[{i+1}/{len(candidates)}] @{c['username']}...")
            if await discovery._validate_candidate(c):
                validated.append(c)
            await asyncio.sleep(1)  # пауза между Gemini-запросами

        logger.info(f"Прошли валидацию: {len(validated)} из {len(candidates)}")

        # 3. Сохраняем в JSON
        out_path = os.path.join("data", f"validated_{profile}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(validated, f, ensure_ascii=False, indent=2)

        logger.info(f"Сохранено в {out_path}")

        # Выводим итог
        print(f"\n{'='*60}")
        print(f"Профиль: {profile}")
        print(f"Кандидатов: {len(candidates)}")
        print(f"Прошли валидацию: {len(validated)}")
        print(f"Сохранено: {out_path}")
        print(f"{'='*60}")
        for v in sorted(validated, key=lambda x: x.get("subscribers", 0), reverse=True):
            subs = v.get("subscribers", 0)
            print(f"  @{v['username']:30s}  {subs:>7} подп.  (из {v.get('source', '?')})")
        print()

    finally:
        await discovery.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=["marketplace", "ai"])
    args = parser.parse_args()
    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
