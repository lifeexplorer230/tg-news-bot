"""Сервис отправки статуса бота в Telegram группу"""
import asyncio
from datetime import datetime
from telethon import TelegramClient
from utils.logger import setup_logger

logger = setup_logger(__name__)


class StatusReporter:
    """Отправка статуса бота в группу"""

    def __init__(self, config, db):
        """
        Инициализация Status Reporter

        Args:
            config: Конфигурация
            db: Database instance
        """
        self.config = config
        self.db = db
        self.status_chat = config.get('status.chat', 'Soft Status')
        self.bot_name = config.get('status.bot_name', 'Marketplace News Bot')

    async def send_status(self):
        """Отправить статус в группу"""
        try:
            # Получаем статистику за сегодня
            stats = self.db.get_today_stats()

            # Формируем сообщение
            now = datetime.now()
            time_str = now.strftime("%H:%M:%S")
            date_str = now.strftime("%d.%m.%Y")

            message = f"🤖 **{self.bot_name} - Статус на {time_str}**\n\n"
            message += f"📅 Дата: {date_str}\n\n"
            message += f"📊 **Статистика за сегодня:**\n"
            message += f"   📥 Собрано новостей: {stats['messages_today']}\n"
            message += f"   ✅ Обработано: {stats['processed_today']}\n"
            message += f"   📝 Опубликовано: {stats['published_today']}\n"
            message += f"   ⏳ В очереди: {stats['unprocessed']}\n\n"
            message += f"📈 **Каналы:**\n"
            message += f"   🔗 Активных каналов: {stats['active_channels']}\n\n"
            message += f"✅ Бот работает нормально"

            # Подключаемся к Telegram с отдельной сессией для статуса
            # Это предотвращает "database is locked" когда listener активен
            status_session = self.config.get('telegram.session_name') + '_status'
            client = TelegramClient(
                status_session,
                self.config.telegram_api_id,
                self.config.telegram_api_hash
            )

            await client.start(phone=self.config.telegram_phone)

            # Отправляем сообщение
            await client.send_message(self.status_chat, message)

            logger.info(f"✅ Статус отправлен в {self.status_chat}")

            await client.disconnect()

        except Exception as e:
            logger.error(f"❌ Ошибка отправки статуса: {e}", exc_info=True)


async def run_status_reporter(config, db):
    """
    Запустить отправку статуса

    Args:
        config: Конфигурация
        db: Database instance
    """
    reporter = StatusReporter(config, db)
    await reporter.send_status()
