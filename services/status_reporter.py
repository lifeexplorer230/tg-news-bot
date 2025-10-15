"""Сервис отправки статуса бота в Telegram группу"""

import time
from pathlib import Path

from telethon import TelegramClient

from database.db import Database
from utils.logger import setup_logger
from utils.telegram_helpers import safe_connect
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
        self.timezone_name = config.get(
            "status.timezone", config.get("processor.timezone", "Europe/Moscow")
        )
        self.timezone = get_timezone(self.timezone_name)
        self.db = db or Database(config.db_path, **config.database_settings())
        self.status_chat = config.get("status.chat", "Soft Status")
        self.bot_name = config.get("status.bot_name", "Marketplace News Bot")
        self.message_template = config.get("status.message_template", "")
        self.heartbeat_path = Path(config.get("listener.heartbeat_path", "./logs/listener.heartbeat"))
        self.heartbeat_max_age = config.get("listener.heartbeat_max_age", 180)

    def _check_listener_status(self) -> dict:
        """
        Проверить состояние Listener через heartbeat файл

        Returns:
            dict с информацией о listener: status, age, status_emoji
        """
        if not self.heartbeat_path.exists():
            return {
                "listener_status": "❌ Не работает",
                "listener_age_seconds": None,
                "listener_status_emoji": "❌",
            }

        try:
            mtime = self.heartbeat_path.stat().st_mtime
            age = time.time() - mtime

            if age > self.heartbeat_max_age:
                return {
                    "listener_status": f"⚠️ Не отвечает ({int(age)}с)",
                    "listener_age_seconds": int(age),
                    "listener_status_emoji": "⚠️",
                }

            return {
                "listener_status": f"✅ Работает ({int(age)}с)",
                "listener_age_seconds": int(age),
                "listener_status_emoji": "✅",
            }

        except OSError:
            return {
                "listener_status": "❌ Ошибка чтения",
                "listener_age_seconds": None,
                "listener_status_emoji": "❌",
            }

    async def send_status(self):
        """Отправить статус в группу"""
        try:
            # Получаем статистику за сегодня (в нужной timezone)
            stats = self.db.get_today_stats(timezone_name=self.timezone_name)

            # Проверяем состояние Listener
            listener_info = self._check_listener_status()

            # Формируем сообщение
            now = now_in_timezone(self.timezone)
            time_str = now.strftime("%H:%M:%S")
            date_str = now.strftime("%d.%m.%Y")

            context = {
                "bot_name": self.bot_name,
                "date": date_str,
                "time": time_str,
                "timezone": self.timezone_name,
                "messages_today": stats.get("messages_today", 0),
                "processed_today": stats.get("processed_today", 0),
                "published_today": stats.get("published_today", 0),
                "unprocessed": stats.get("unprocessed", 0),
                "active_channels": stats.get("active_channels", 0),
                "total_messages": stats.get("total_messages", 0),
                "total_published": stats.get("total_published", 0),
                **listener_info,  # Добавляем информацию о listener
            }

            template = (self.message_template or "").strip()
            if template:
                try:
                    message = template.format(**context)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось подставить параметры в status.message_template: %s", exc)
                    message = self._build_default_message(context)
            else:
                message = self._build_default_message(context)

            # Проверяем наличие bot_token для избежания конфликтов сессий
            bot_token = self.config.get("status.bot_token", "").strip()

            if bot_token:
                # Используем Bot API (рекомендуется)
                # Это избегает конфликтов с listener который использует User API
                client = TelegramClient(
                    "status_bot",  # Имя сессии для бота
                    self.config.telegram_api_id,
                    self.config.telegram_api_hash,
                )
                await client.start(bot_token=bot_token)
                logger.debug("StatusReporter использует Bot API (избегает конфликтов сессий)")
            else:
                # Fallback: используем User API с основной сессией
                # Используем ту же сессию что и listener для избежания конфликтов
                logger.warning(
                    "⚠️ StatusReporter использует User API - рекомендуется задать status.bot_token в config.yaml"
                )
                session_name = self.config.get("telegram.session_name")
                client = TelegramClient(
                    session_name, self.config.telegram_api_id, self.config.telegram_api_hash
                )
                await safe_connect(client, session_name)

            # QA-6: Гарантируем disconnect даже при исключении
            try:
                # Отправляем сообщение
                await client.send_message(self.status_chat, message)
                logger.info(f"✅ Статус отправлен в {self.status_chat}")
            finally:
                # Гарантированно отключаемся от клиента
                await client.disconnect()
                logger.debug("StatusReporter: client disconnected")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки статуса: {e}", exc_info=True)
        finally:
            if self._owns_db:
                self.db.close()

    @staticmethod
    def _build_default_message(context: dict) -> str:
        message = (
            f"🤖 **{context['bot_name']} - Статус на {context['time']}**\n\n"
            f"📅 Дата: {context['date']}\n\n"
            "📊 **Статистика за сегодня:**\n"
            f"   📥 Собрано новостей: {context['messages_today']}\n"
            f"   ✅ Обработано: {context['processed_today']}\n"
            f"   📝 Опубликовано: {context['published_today']}\n"
            f"   ⏳ В очереди: {context['unprocessed']}\n\n"
            "📈 **Каналы:**\n"
            f"   🔗 Активных каналов: {context['active_channels']}\n\n"
            "🎧 **Listener:**\n"
            f"   {context['listener_status']}\n\n"
            f"{context['listener_status_emoji']} Бот работает"
        )
        return message

    def __del__(self):
        """Cleanup on garbage collection"""
        if self._owns_db:
            try:
                self.db.close()
            except Exception:
                pass  # Suppress errors during cleanup


async def run_status_reporter(config, db=None):
    """
    Запустить отправку статуса

    Args:
        config: Конфигурация
        db: Database instance (опционально)
    """
    reporter = StatusReporter(config, db)
    await reporter.send_status()
