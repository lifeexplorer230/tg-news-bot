#!/usr/bin/env python3
"""Быстрая авторизация с кодом и паролем"""
import asyncio
import sys
from telethon import TelegramClient
from utils.config import load_config

async def quick_auth(code: str, password: str = None):
    """Авторизация с готовым кодом"""
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

        print(f"🔑 Используем код: {code}")
        try:
            await client.sign_in(config.telegram_phone, code)
            print("✅ Авторизация успешна!")
        except Exception as e:
            if "password" in str(e).lower() or "2fa" in str(e).lower():
                print(f"🔐 Используем пароль 2FA")
                if password:
                    await client.sign_in(password=password)
                    print("✅ Авторизация с 2FA успешна!")
                else:
                    print("❌ Требуется пароль 2FA, но не предоставлен")
                    await client.disconnect()
                    return False
            else:
                print(f"❌ Ошибка: {e}")
                await client.disconnect()
                raise
    else:
        print("✅ Уже авторизован!")

    me = await client.get_me()
    print(f"👤 Вошли как: {me.first_name} (ID: {me.id})")

    await client.disconnect()
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 quick_auth.py <code> [password]")
        sys.exit(1)

    code = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None

    success = asyncio.run(quick_auth(code, password))
    sys.exit(0 if success else 1)
