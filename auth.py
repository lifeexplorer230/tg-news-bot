#!/usr/bin/env python3
"""Скрипт авторизации Telegram"""
import asyncio
import logging

from telethon import TelegramClient

from utils.config import load_config
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def authorize():
    """Авторизация в Telegram"""
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

        logger.info("✉️ Код отправлен! Введите код из Telegram:")
        code = input("Код: ").strip()

        try:
            await client.sign_in(config.telegram_phone, code)
            logger.info("✅ Авторизация успешна!")
        except Exception as e:
            if "password" in str(e).lower() or "2fa" in str(e).lower():
                logger.warning("🔐 Требуется 2FA пароль")
                password = input("Пароль 2FA: ").strip()
                await client.sign_in(password=password)
                logger.info("✅ Авторизация с 2FA успешна!")
            else:
                logger.error("❌ Ошибка авторизации: %s", e)
                raise
    else:
        logger.info("✅ Уже авторизован!")

    me = await client.get_me()
    logger.info("👤 Вошли как: %s (@%s)", me.first_name, me.username)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(authorize())
