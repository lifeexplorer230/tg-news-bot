"""Сервис отправки статуса бота в Telegram группу"""
import asyncio

from telethon import TelegramClient

from database.db import Database
from utils.logger import setup_logger
from utils.timezone import get_timezone, now_in_timezone

logger = setup_logger(__name__)


class StatusReporter:
    """Отправка статуса бота в группу"""

    def __init__(self, config, db=None):
        """
        Инициализация Status Reporter

        Args:
            config: Конфигурация
            db: Database instance (опционально)
        """
        self.config = config
        self._owns_db = db is None
        self.timezone_name = config.get('status.timezone', config.get('processor.timezone', 'Europe/Moscow'))
        self.timezone = get_timezone(self.timezone_name)
        self.db = db or Database(config.db_path, self.timezone_name)
        self.status_chat = config.get('status.chat', 'Soft Status')
        self.bot_name = config.get('status.bot_name', 'Marketplace News Bot')

    async def send_status(self):
        """Отправить статус в группу"""
        try:
            # Получаем статистику за сегодня
            stats = self.db.get_today_stats()

            # Формируем сообщение
            now = now_in_timezone(self.timezone)
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

            # Проверяем наличие bot_token для избежания конфликтов сессий
            bot_token = self.config.get('status.bot_token', '').strip()

            if bot_token:
                # Используем Bot API (рекомендуется)
                # Это избегает конфликтов с listener который использует User API
                client = TelegramClient(
                    'status_bot',  # Имя сессии для бота
                    self.config.telegram_api_id,
                    self.config.telegram_api_hash
                )
                await client.start(bot_token=bot_token)
                logger.debug("StatusReporter использует Bot API (избегает конфликтов сессий)")
            else:
                # Fallback: используем User API с отдельной сессией
                # ВНИМАНИЕ: может конфликтовать с listener если он активен!
                logger.warning("⚠️ StatusReporter использует User API - может конфликтовать с listener! "
                             "Рекомендуется задать status.bot_token в config.yaml")
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
        finally:
            if self._owns_db:
                self.db.close()


async def run_status_reporter(config, db=None):
    """
    Запустить отправку статуса

    Args:
        config: Конфигурация
        db: Database instance (опционально)
    """
    reporter = StatusReporter(config, db)
    await reporter.send_status()
