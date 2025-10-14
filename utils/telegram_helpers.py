"""Вспомогательные функции для работы с Telegram API"""

import asyncio
import logging
from contextlib import suppress
from telethon import TelegramClient
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)


async def safe_connect(client: TelegramClient, session_name: str, max_wait: int = 3600) -> bool:
    """
    Безопасное подключение к Telegram с обработкой FloodWait.

    Args:
        client: Telegram client
        session_name: Имя сессии для логирования
        max_wait: Максимальное время ожидания в секундах (по умолчанию 1 час)

    Returns:
        True если подключение успешно, False в противном случае

    Raises:
        RuntimeError: Если FloodWait превышает max_wait или сессия не авторизована
    """
    try:
        await client.connect()

        # Проверяем авторизацию
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                f"Telegram сессия '{session_name}' не авторизована. "
                "Выполните 'python auth.py' перед запуском."
            )

        logger.info(f"✅ Подключение к Telegram установлено (сессия: {session_name})")
        return True

    except FloodWaitError as e:
        wait_seconds = e.seconds

        if wait_seconds > max_wait:
            logger.error(
                f"❌ FloodWait {wait_seconds}s превышает максимальное время ожидания {max_wait}s. "
                "Остановите приложение и дождитесь истечения блокировки."
            )
            with suppress(Exception):
                await client.disconnect()
            raise RuntimeError(
                f"FloodWait {wait_seconds}s слишком велик. Требуется ручное ожидание."
            ) from e

        logger.warning(
            f"⏳ FloodWait {wait_seconds}s при подключении к Telegram. "
            f"Автоматически ожидаем {wait_seconds} секунд..."
        )

        # Ждём с прогрессом
        for remaining in range(wait_seconds, 0, -10):
            if remaining <= 10:
                await asyncio.sleep(remaining)
                break
            logger.info(f"⏳ Осталось {remaining} секунд...")
            await asyncio.sleep(10)

        # Пытаемся переподключиться
        logger.info("🔄 Повторное подключение после FloodWait...")
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                f"Telegram сессия '{session_name}' не авторизована после FloodWait."
            )

        logger.info("✅ Успешное подключение после FloodWait")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Telegram: {e}", exc_info=True)
        with suppress(Exception):
            await client.disconnect()
        raise
