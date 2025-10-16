"""Сервис отправки статуса бота в Telegram группу"""

import time
from datetime import timedelta
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
        self.heartbeat_path = Path(config.get("listener.healthcheck.heartbeat_path", "./logs/listener.heartbeat"))
        self.heartbeat_max_age = config.get("listener.healthcheck.max_age_seconds", 180)

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

    def _calculate_next_status_time(self) -> str:
        """
        Вычислить время следующей отправки статуса

        Returns:
            str: Строка с временем следующего статуса
        """
        interval_minutes = self.config.get("status.interval_minutes", 60)

        try:
            # Получаем текущее время в нужной timezone
            now = now_in_timezone(self.timezone)

            # Добавляем интервал
            next_status = now + timedelta(minutes=interval_minutes)

            # Форматируем результат
            return f"через {interval_minutes} мин ({next_status.strftime('%H:%M')})"

        except (ValueError, TypeError) as e:
            logger.error(f"Ошибка при вычислении времени следующего статуса: {e}", exc_info=True)
            return "неизвестно"
        except Exception as e:
            logger.error(f"Неожиданная ошибка при вычислении времени следующего статуса: {e}", exc_info=True)
            return "неизвестно"

    def _calculate_next_processor_time(self) -> str:
        """
        Вычислить время следующего запуска processor

        Returns:
            str: Строка с временем и датой следующего запуска
        """
        # Получаем schedule_time из конфига (например "08:00")
        schedule_time_str = self.config.get("processor.schedule_time", "09:00")

        try:
            # Парсим время
            hour, minute = map(int, schedule_time_str.split(":"))
        except ValueError as e:
            logger.error(f"Неверный формат schedule_time '{schedule_time_str}': {e}")
            return "неизвестно (ошибка конфигурации)"

        try:
            # Получаем текущее время в нужной timezone
            now = now_in_timezone(self.timezone)

            # Создаем datetime для следующего запуска сегодня
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Если время уже прошло сегодня, берем завтра
            if next_run <= now:
                next_run = next_run + timedelta(days=1)

            # Форматируем результат
            if next_run.date() == now.date():
                return f"сегодня в {next_run.strftime('%H:%M')}"
            else:
                return f"завтра в {next_run.strftime('%H:%M')}"

        except (ValueError, TypeError) as e:
            logger.error(f"Ошибка при вычислении времени следующего запуска: {e}", exc_info=True)
            return "неизвестно"
        except Exception as e:
            logger.error(f"Неожиданная ошибка при вычислении времени следующего запуска: {e}", exc_info=True)
            return "неизвестно"

    async def send_status(self):
        """Отправить статус в группу"""
        try:
            # Получаем статистику за сегодня (в нужной timezone)
            stats = self.db.get_today_stats(timezone_name=self.timezone_name)

            # Проверяем состояние Listener
            listener_info = self._check_listener_status()

            # Вычисляем время следующей отправки статуса
            next_status_time = self._calculate_next_status_time()

            # Вычисляем время следующего запуска processor
            next_processor_time = self._calculate_next_processor_time()

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
                "next_status_time": next_status_time,
                "next_processor_time": next_processor_time,
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
            "⏰ **Следующий статус:**\n"
            f"   {context['next_status_time']}\n\n"
            "📰 **Следующий дайджест:**\n"
            f"   {context['next_processor_time']}\n\n"
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
