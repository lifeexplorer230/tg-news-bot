"""Постоянный мониторинг Telegram каналов"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import Channel

from database.db import Database
from utils.config import Config
from utils.logger import setup_logger
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
        whitelist = config.get("listener.channel_whitelist", [])
        blacklist = config.get("listener.channel_blacklist", [])

        # Инициализация Telegram клиента
        self.client = TelegramClient(
            config.get("telegram.session_name"), config.telegram_api_id, config.telegram_api_hash
        )

        self.min_message_length = config.get("listener.min_message_length", 50)
        self.exclude_keywords = [
            self._normalize_text(keyword)
            for keyword in config.get("filters.exclude_keywords", [])
            if keyword
        ]
        self.channel_ids = []
        self._channel_id_set = set()
        self.channel_whitelist = {self._normalize_channel(value) for value in whitelist if value}
        self.channel_blacklist = {self._normalize_channel(value) for value in blacklist if value}
        self.heartbeat_path = Path(
            self.config.get(
                "listener.healthcheck.heartbeat_path",
                "./logs/listener.heartbeat",
            )
        ).resolve()
        self.heartbeat_interval = max(
            5,
            int(self.config.get("listener.healthcheck.interval_seconds", 60)),
        )
        self._heartbeat_task: asyncio.Task | None = None

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

        self._start_heartbeat()

        # Запускаем бесконечный цикл
        try:
            await self.client.run_until_disconnected()
        finally:
            await self._stop_heartbeat()

    async def load_channels(self):
        """Загрузить каналы из подписок пользователя"""
        logger.info("Загрузка каналов из подписок...")

        dialogs = await self.client.get_dialogs()
        channel_count = 0
        skipped_blacklist = 0
        skipped_not_whitelisted = 0

        for dialog in dialogs:
            # Проверяем что это канал
            if isinstance(dialog.entity, Channel) and dialog.entity.broadcast:
                username = dialog.entity.username or str(dialog.entity.id)
                title = dialog.entity.title
                if not self._is_channel_allowed(username, dialog.entity.id):
                    if (
                        self.channel_blacklist
                        and self._normalize_channel(username or dialog.entity.id)
                        in self.channel_blacklist
                    ):
                        skipped_blacklist += 1
                        logger.debug(f"Канал исключён blacklist: @{username} - {title}")
                    else:
                        skipped_not_whitelisted += 1
                        logger.debug(f"Канал не входит в whitelist: @{username} - {title}")
                    continue

                # Добавляем в БД
                self.db.add_channel(username, title)
                if dialog.entity.id not in self._channel_id_set:
                    self.channel_ids.append(dialog.entity.id)
                    self._channel_id_set.add(dialog.entity.id)
                    channel_count += 1

                logger.info(f"Канал добавлен: @{username} - {title}")

        logger.info(f"Загружено {channel_count} каналов")
        if skipped_blacklist:
            logger.info(f"Пропущено каналов по blacklist: {skipped_blacklist}")
        if skipped_not_whitelisted:
            logger.info(f"Пропущено каналов вне whitelist: {skipped_not_whitelisted}")

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
            normalized_text = self._normalize_text(text)
            if any(keyword in normalized_text for keyword in self.exclude_keywords):
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
                has_media=has_media,
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
        await self._stop_heartbeat()
        self.db.close()

    @staticmethod
    def _normalize_channel(value) -> str:
        """Нормализовать обозначение канала для сравнения"""
        return str(value).lstrip("@").lower()

    def _is_channel_allowed(self, username: str, channel_id: int) -> bool:
        """Проверить что канал разрешён для прослушивания"""
        identifier = self._normalize_channel(username or channel_id)

        if self.channel_blacklist and identifier in self.channel_blacklist:
            return False
        if self.channel_whitelist and identifier not in self.channel_whitelist:
            return False
        return True

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Привести текст к нижнему регистру без лишних пробелов"""
        return value.lower().strip()

    def _start_heartbeat(self) -> None:
        """Запустить периодическое обновление heartbeat файла."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        """Остановить heartbeat и удалить файл."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        with suppress(FileNotFoundError):
            self.heartbeat_path.unlink()

    async def _heartbeat_loop(self) -> None:
        """Периодически обновлять heartbeat файл."""
        while True:
            self._write_heartbeat()
            await asyncio.sleep(self.heartbeat_interval)

    def _write_heartbeat(self) -> None:
        """Обновить файл heartbeat свежей меткой времени."""
        try:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(datetime.now(UTC).isoformat())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось обновить heartbeat: %s", exc)


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
