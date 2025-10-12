#!/usr/bin/env python3
"""Быстрая авторизация с кодом и паролем"""
from __future__ import annotations

import asyncio
import logging
import sys

from telethon import TelegramClient

from utils.config import load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def quick_auth(code: str, password: str | None = None) -> bool:
    """Авторизация с готовым кодом"""
    config = load_config()
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    client = TelegramClient(
        config.get("telegram.session_name", "marketplace_bot_session"),
        config.telegram_api_id,
        config.telegram_api_hash,
    )

    await client.connect()

    if not await client.is_user_authorized():
        logger.info("📱 Отправляем код на %s", config.telegram_phone)
        await client.send_code_request(config.telegram_phone)

        logger.info("🔑 Используем код: %s", code)
        try:
            await client.sign_in(config.telegram_phone, code)
            logger.info("✅ Авторизация успешна!")
        except Exception as e:
            if "password" in str(e).lower() or "2fa" in str(e).lower():
                logger.warning("🔐 Требуется пароль 2FA")
                if password:
                    await client.sign_in(password=password)
                    logger.info("✅ Авторизация с 2FA успешна!")
                else:
                    logger.error("❌ Требуется пароль 2FA, но не предоставлен")
                    await client.disconnect()
                    return False
            else:
                logger.error("❌ Ошибка авторизации: %s", e)
                await client.disconnect()
                raise
    else:
        logger.info("✅ Уже авторизован!")

    me = await client.get_me()
    logger.info("👤 Вошли как: %s (ID: %s)", me.first_name, me.id)

    await client.disconnect()
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: python3 quick_auth.py <code> [password]")
        sys.exit(1)

    code = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None

    success = asyncio.run(quick_auth(code, password))
    sys.exit(0 if success else 1)
