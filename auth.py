#!/usr/bin/env python3
"""Скрипт авторизации Telegram"""
import asyncio
import sys
from telethon import TelegramClient
from utils.config import load_config

async def authorize():
    """Авторизация в Telegram"""
    config = load_config()

    client = TelegramClient(
        config.get('telegram.session_name', 'marketplace_bot_session'),
        config.telegram_api_id,
        config.telegram_api_hash
    )

    await client.connect()

    if not await client.is_user_authorized():
        print(f"📱 Отправляем код на {config.telegram_phone}")
        await client.send_code_request(config.telegram_phone)

        print("✉️ Код отправлен! Введите код из Telegram:")
        code = input("Код: ").strip()

        try:
            await client.sign_in(config.telegram_phone, code)
            print("✅ Авторизация успешна!")
        except Exception as e:
            if "password" in str(e).lower() or "2fa" in str(e).lower():
                print("🔐 Требуется 2FA пароль")
                password = input("Пароль 2FA: ").strip()
                await client.sign_in(password=password)
                print("✅ Авторизация с 2FA успешна!")
            else:
                print(f"❌ Ошибка: {e}")
                raise
    else:
        print("✅ Уже авторизован!")

    me = await client.get_me()
    print(f"👤 Вошли как: {me.first_name} (@{me.username})")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(authorize())
