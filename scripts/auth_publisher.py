#!/usr/bin/env python3
"""
Одноразовый скрипт авторизации publisher-аккаунта (+79776200940).
Запускать вручную: python scripts/auth_publisher.py
После успешной авторизации сессия будет сохранена в sessions/publisher/processor.session
"""
import asyncio
import os
import sys

# Загружаем .env
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
sys.path.insert(0, project_dir)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_dir, ".env"))
except ImportError:
    pass

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE = os.getenv("PUBLISHER_TELEGRAM_PHONE", "+79776200940")
SESSION_PATH = os.path.join(project_dir, "sessions", "publisher", "processor")

async def main():
    os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
    print(f"Авторизация publisher-аккаунта {PHONE}")
    print(f"Сессия будет сохранена в: {SESSION_PATH}.session")

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован как: {me.first_name} ({me.phone})")
    else:
        await client.send_code_request(PHONE)
        code = input(f"Введите код из SMS/Telegram для {PHONE}: ").strip()
        try:
            await client.sign_in(PHONE, code)
        except SessionPasswordNeededError:
            password = input("Введите пароль двухфакторной аутентификации: ").strip()
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"Успешно авторизован как: {me.first_name} ({me.phone})")

    # Кешируем entity каналов, чтобы избежать ResolveUsernameRequest при публикации
    print("Кешируем entity каналов публикации...")
    for channel in ["@rnpii", "@rnpozwb"]:
        try:
            entity = await client.get_entity(channel)
            print(f"  {channel} → ID {entity.id} ✓")
        except Exception as e:
            print(f"  {channel} → ошибка: {e}")

    await client.disconnect()
    print("Готово! Сессия сохранена.")

if __name__ == "__main__":
    asyncio.run(main())
