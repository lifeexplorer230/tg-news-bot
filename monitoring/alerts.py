"""
Система алертов для отправки уведомлений в Telegram

Поддерживает:
- Уровни: INFO, WARNING, ERROR, CRITICAL
- Rate limiting для предотвращения спама
- Форматирование с emoji и контекстом
- Асинхронная отправка
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from utils.logger import setup_logger

logger = setup_logger(__name__)


class AlertLevel(Enum):
    """Уровни критичности алертов"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """Алерт для отправки"""
    level: AlertLevel
    title: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RateLimitState:
    """Состояние rate limiter для конкретного типа алертов"""
    last_sent: float = 0.0
    count_in_window: int = 0
    window_start: float = 0.0


class AlertManager:
    """
    Менеджер алертов с поддержкой rate limiting

    Features:
    - Асинхронная отправка в Telegram
    - Rate limiting по типам алертов
    - Форматирование с emoji
    - Группировка алертов в окнах времени
    - Graceful degradation при ошибках
    """

    # Emoji для каждого уровня
    LEVEL_EMOJI = {
        AlertLevel.INFO: "ℹ️",
        AlertLevel.WARNING: "⚠️",
        AlertLevel.ERROR: "❌",
        AlertLevel.CRITICAL: "🚨",
    }

    # Rate limits: (max_per_window, window_seconds, min_interval)
    RATE_LIMITS = {
        AlertLevel.INFO: (10, 3600, 60),        # 10/час, мин. 60 сек между сообщениями
        AlertLevel.WARNING: (20, 3600, 30),     # 20/час, мин. 30 сек между сообщениями
        AlertLevel.ERROR: (50, 3600, 10),       # 50/час, мин. 10 сек между сообщениями
        AlertLevel.CRITICAL: (100, 3600, 5),    # 100/час, мин. 5 сек между сообщениями
    }

    def __init__(
        self,
        client: TelegramClient,
        target_chat: str,
        bot_name: str = "News Bot",
        enabled: bool = True,
    ):
        """
        Инициализация менеджера алертов

        Args:
            client: Telegram клиент
            target_chat: Чат для отправки алертов (username или ID)
            bot_name: Имя бота для отображения в сообщениях
            enabled: Включены ли алерты (для возможности отключения)
        """
        self.client = client
        self.target_chat = target_chat
        self.bot_name = bot_name
        self.enabled = enabled

        # Rate limiting state для каждого уровня
        self._rate_limits: dict[AlertLevel, RateLimitState] = {
            level: RateLimitState() for level in AlertLevel
        }

        # Очередь алертов для асинхронной отправки
        self._queue: asyncio.Queue[Alert] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"AlertManager initialized: target={target_chat}, "
            f"bot_name={bot_name}, enabled={enabled}"
        )

    async def start(self):
        """Запустить worker для обработки очереди алертов"""
        if not self.enabled:
            logger.info("AlertManager disabled, worker not started")
            return

        if self._worker_task is not None:
            logger.warning("AlertManager worker already running")
            return

        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("AlertManager worker started")

    async def stop(self):
        """Остановить worker и дождаться обработки всех алертов"""
        if self._worker_task is None:
            return

        # Сигнал остановки
        self._shutdown_event.set()

        # Ждем завершения worker
        try:
            await asyncio.wait_for(self._worker_task, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("AlertManager worker shutdown timeout")
            self._worker_task.cancel()

        self._worker_task = None
        logger.info("AlertManager worker stopped")

    async def send_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        context: dict[str, Any] | None = None,
    ):
        """
        Отправить алерт (добавить в очередь)

        Args:
            level: Уровень критичности
            title: Заголовок алерта
            message: Основное сообщение
            context: Дополнительный контекст (будет отформатирован)
        """
        if not self.enabled:
            logger.debug(f"Alert skipped (disabled): {level.value} - {title}")
            return

        alert = Alert(
            level=level,
            title=title,
            message=message,
            context=context or {},
        )

        await self._queue.put(alert)
        logger.debug(f"Alert queued: {level.value} - {title}")

    async def info(self, title: str, message: str, context: dict[str, Any] | None = None):
        """Отправить INFO алерт"""
        await self.send_alert(AlertLevel.INFO, title, message, context)

    async def warning(self, title: str, message: str, context: dict[str, Any] | None = None):
        """Отправить WARNING алерт"""
        await self.send_alert(AlertLevel.WARNING, title, message, context)

    async def error(self, title: str, message: str, context: dict[str, Any] | None = None):
        """Отправить ERROR алерт"""
        await self.send_alert(AlertLevel.ERROR, title, message, context)

    async def critical(self, title: str, message: str, context: dict[str, Any] | None = None):
        """Отправить CRITICAL алерт"""
        await self.send_alert(AlertLevel.CRITICAL, title, message, context)

    def _should_send_alert(self, level: AlertLevel) -> tuple[bool, str | None]:
        """
        Проверить, можно ли отправить алерт с учетом rate limits

        Returns:
            (should_send, reason_if_not)
        """
        max_per_window, window_seconds, min_interval = self.RATE_LIMITS[level]
        state = self._rate_limits[level]
        current_time = time.time()

        # Проверка минимального интервала
        if current_time - state.last_sent < min_interval:
            return False, f"min_interval not reached (last sent {current_time - state.last_sent:.1f}s ago)"

        # Сброс окна, если прошло достаточно времени
        if current_time - state.window_start > window_seconds:
            state.window_start = current_time
            state.count_in_window = 0

        # Проверка лимита в окне
        if state.count_in_window >= max_per_window:
            return False, f"rate limit exceeded ({state.count_in_window}/{max_per_window} in window)"

        return True, None

    def _format_alert(self, alert: Alert) -> str:
        """
        Форматировать алерт для отправки в Telegram

        Args:
            alert: Алерт для форматирования

        Returns:
            Отформатированное сообщение
        """
        emoji = self.LEVEL_EMOJI[alert.level]
        timestamp = alert.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            f"{emoji} <b>{alert.level.value}</b>",
            f"<b>{alert.title}</b>",
            "",
            alert.message,
        ]

        # Добавляем контекст, если есть
        if alert.context:
            lines.append("")
            lines.append("<b>Context:</b>")
            for key, value in alert.context.items():
                # Ограничиваем длину значений
                value_str = str(value)
                if len(value_str) > 200:
                    value_str = value_str[:197] + "..."
                lines.append(f"  • {key}: {value_str}")

        # Добавляем метаданные
        lines.extend([
            "",
            f"<i>{self.bot_name} | {timestamp}</i>",
        ])

        return "\n".join(lines)

    async def _send_to_telegram(self, alert: Alert) -> bool:
        """
        Отправить алерт в Telegram

        Args:
            alert: Алерт для отправки

        Returns:
            True если успешно, False если ошибка
        """
        try:
            formatted = self._format_alert(alert)

            await self.client.send_message(
                self.target_chat,
                formatted,
                parse_mode="html",
            )

            logger.debug(f"Alert sent: {alert.level.value} - {alert.title}")
            return True

        except FloodWaitError as e:
            logger.warning(f"FloodWait error sending alert: wait {e.seconds}s")
            # Ждем и пробуем еще раз
            await asyncio.sleep(e.seconds)
            try:
                formatted = self._format_alert(alert)
                await self.client.send_message(
                    self.target_chat,
                    formatted,
                    parse_mode="html",
                )
                return True
            except Exception as retry_error:
                logger.error(f"Failed to send alert after FloodWait: {retry_error}")
                return False

        except RPCError as e:
            logger.error(f"Telegram RPC error sending alert: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error sending alert: {e}", exc_info=True)
            return False

    async def _worker(self):
        """Worker для обработки очереди алертов"""
        logger.info("AlertManager worker loop started")

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Ждем алерт с таймаутом для проверки shutdown
                    alert = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Проверяем rate limit
                should_send, reason = self._should_send_alert(alert.level)

                if not should_send:
                    logger.debug(
                        f"Alert dropped due to rate limit: "
                        f"{alert.level.value} - {alert.title} ({reason})"
                    )
                    continue

                # Отправляем алерт
                success = await self._send_to_telegram(alert)

                if success:
                    # Обновляем rate limit state
                    state = self._rate_limits[alert.level]
                    state.last_sent = time.time()
                    state.count_in_window += 1

                # Помечаем задачу как выполненную
                self._queue.task_done()

            # После shutdown обрабатываем оставшиеся алерты
            while not self._queue.empty():
                try:
                    alert = self._queue.get_nowait()
                    should_send, _ = self._should_send_alert(alert.level)
                    if should_send:
                        await self._send_to_telegram(alert)
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break

        except Exception as e:
            logger.error(f"AlertManager worker crashed: {e}", exc_info=True)

        finally:
            logger.info("AlertManager worker loop stopped")

    async def __aenter__(self):
        """Context manager support"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager support"""
        await self.stop()
        return False


# Глобальный экземпляр (singleton)
_alert_manager: AlertManager | None = None


def init_alert_manager(
    client: TelegramClient,
    target_chat: str,
    bot_name: str = "News Bot",
    enabled: bool = True,
) -> AlertManager:
    """
    Инициализировать глобальный AlertManager

    Args:
        client: Telegram клиент
        target_chat: Чат для алертов
        bot_name: Имя бота
        enabled: Включены ли алерты

    Returns:
        Инициализированный AlertManager
    """
    global _alert_manager
    _alert_manager = AlertManager(client, target_chat, bot_name, enabled)
    return _alert_manager


def get_alert_manager() -> AlertManager | None:
    """
    Получить глобальный AlertManager

    Returns:
        AlertManager или None если не инициализирован
    """
    return _alert_manager


__all__ = [
    "AlertLevel",
    "Alert",
    "AlertManager",
    "init_alert_manager",
    "get_alert_manager",
]
