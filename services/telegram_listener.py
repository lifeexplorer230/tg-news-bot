"""Постоянный мониторинг Telegram каналов"""
import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.tl.types import Channel
from typing import List
from database.db import Database
from utils.logger import setup_logger
from utils.config import Config
from utils.timezone import now_utc

logger = setup_logger(__name__)


class TelegramListener:
    """Слушатель Telegram каналов"""

    def __init__(self, config: Config, db: Database):
        """
        Инициализация слушателя

        Args:
            config: Конфигурация
            db: База данных
        """
        self.config = config
        self.db = db

        # Инициализация Telegram клиента
        self.client = TelegramClient(
            config.get('telegram.session_name'),
            config.telegram_api_id,
            config.telegram_api_hash
        )

        self.min_message_length = config.get('listener.min_message_length', 50)
        self.exclude_keywords = config.get('filters.exclude_keywords', [])
        self.channel_ids = []

    async def start(self):
        """Запустить слушатель"""
        logger.info("Запуск Telegram слушателя...")

        # Подключаемся
        await self.client.start(phone=self.config.telegram_phone)
        logger.info("Подключение к Telegram установлено")

        # Загружаем каналы из подписок
        await self.load_channels()

        # Регистрируем обработчик новых сообщений
        @self.client.on(events.NewMessage(chats=self.channel_ids))
        async def handler(event):
            await self.handle_new_message(event)

        logger.info(f"Слушаем {len(self.channel_ids)} каналов...")
        logger.info("Listener запущен. Нажмите Ctrl+C для остановки.")

        # Запускаем бесконечный цикл
        await self.client.run_until_disconnected()

    async def load_channels(self):
        """Загрузить каналы из подписок пользователя"""
        logger.info("Загрузка каналов из подписок...")

        dialogs = await self.client.get_dialogs()
        channel_count = 0

        for dialog in dialogs:
            # Проверяем что это канал
            if isinstance(dialog.entity, Channel) and dialog.entity.broadcast:
                username = dialog.entity.username or str(dialog.entity.id)
                title = dialog.entity.title

                # Добавляем в БД
                channel_id = self.db.add_channel(username, title)
                self.channel_ids.append(dialog.entity.id)
                channel_count += 1

                logger.info(f"Канал добавлен: @{username} - {title}")

        logger.info(f"Загружено {channel_count} каналов")

    async def handle_new_message(self, event):
        """
        Обработать новое сообщение из канала

        Args:
            event: Событие нового сообщения
        """
        try:
            message = event.message

            # Проверяем что есть текст
            if not message.text:
                return

            text = message.text.strip()

            # Фильтры
            if len(text) < self.min_message_length:
                return

            # Проверка на исключаемые ключевые слова
            if any(keyword.lower() in text.lower() for keyword in self.exclude_keywords):
                logger.debug(f"Сообщение пропущено (фильтр): {text[:50]}...")
                return

            # Проверяем что сообщение не старше 24 часов (для случая reconnect)
            if message.date < now_utc() - timedelta(hours=24):
                return

            # Получаем информацию о канале
            chat = await event.get_chat()
            username = chat.username or str(chat.id)

            # Получаем channel_id из БД
            channel_id = self.db.get_channel_id(username)
            if not channel_id:
                # Если канала нет в БД (странно), добавляем
                channel_id = self.db.add_channel(username, chat.title)

            # Сохраняем сообщение
            has_media = message.media is not None
            saved_id = self.db.save_message(
                channel_id=channel_id,
                message_id=message.id,
                text=text,
                date=message.date,
                has_media=has_media
            )

            if saved_id:
                logger.info(f"Сохранено: @{username} | {text[:50]}...")
            # Если None - значит уже есть в БД

        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")

    async def stop(self):
        """Остановить слушатель"""
        logger.info("Остановка Telegram слушателя...")
        await self.client.disconnect()
        self.db.close()


async def run_listener(config: Config, db: Database):
    """
    Запустить listener

    Args:
        config: Конфигурация
        db: База данных
    """
    listener = TelegramListener(config, db)
    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        await listener.stop()
    except Exception as e:
        logger.error(f"Ошибка в listener: {e}")
        await listener.stop()
