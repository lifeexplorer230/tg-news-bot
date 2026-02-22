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
from utils.telegram_helpers import safe_connect
from utils.timezone import now_utc
from utils.sanitization import sanitize_text, sanitize_channel_name, is_safe_for_storage

logger = setup_logger(__name__)


class TelegramListener:
    """Слушатель Telegram каналов"""

    # Security: Максимальный размер входящего сообщения (100KB)
    MAX_MESSAGE_SIZE = 100000

    def __init__(self, config: Config):
        """
        Инициализация слушателя

        Args:
            config: Конфигурация
        """
        self.config = config
        self.db = Database(config.db_path, **config.database_settings())
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
        self.mode = str(config.get("listener.mode", "subscriptions")).lower()
        if self.mode not in {"subscriptions", "manual"}:
            logger.warning(
                "Неизвестный режим listener '%s', переключаемся на subscriptions",
                self.mode,
            )
            self.mode = "subscriptions"

        manual_channels = config.get("listener.manual_channels", []) or []
        self.manual_channels: list[str] = []
        seen_manual: set[str] = set()
        for raw_value in manual_channels:
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value.startswith("@"):
                value = value[1:]
            if not value:
                continue
            lower = value.lower()
            if lower in seen_manual:
                continue
            seen_manual.add(lower)
            self.manual_channels.append(value)
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
        session_name = self.config.get("telegram.session_name")
        await safe_connect(self.client, session_name)
        logger.info("Подключение к Telegram установлено")

        # Загружаем каналы из подписок
        await self.load_channels()

        if not self.channel_ids:
            raise RuntimeError(
                f"Не найдено каналов для прослушивания (mode={self.mode}). Проверьте конфигурацию."
            )

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
        """Загрузить список каналов согласно конфигурации."""
        self.channel_ids = []
        self._channel_id_set = set()
        if self.mode == "manual":
            await self._load_manual_channels()
        else:
            await self._load_subscription_channels()

    async def _load_subscription_channels(self):
        """Загрузить каналы из подписок пользователя."""
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

                # QA-3: Добавляем в БД неблокирующим способом
                await asyncio.to_thread(self.db.add_channel, username, title)
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

    async def _load_manual_channels(self):
        """Загрузить каналы, указанные в конфигурации."""
        logger.info("Загрузка каналов из конфигурации (manual)...")

        if not self.manual_channels:
            logger.warning(
                "listener.manual_channels пуст — manual режим не сможет принимать сообщения"
            )
            return

        channel_count = 0
        skipped_blacklist = 0
        skipped_errors = 0
        skipped_duplicates = 0

        for entry in self.manual_channels:
            query = entry
            if entry.isdigit():
                try:
                    query = int(entry)
                except ValueError:
                    query = entry

            try:
                entity = await self.client.get_entity(query)
            except Exception as exc:  # noqa: BLE001
                skipped_errors += 1
                logger.error("Не удалось получить канал %s: %s", entry, exc)
                continue

            if not isinstance(entity, Channel) or not entity.broadcast:
                skipped_errors += 1
                logger.warning("Объект %s не является публичным каналом", entry)
                continue

            username = entity.username or str(entity.id)
            title = entity.title

            if not self._is_channel_allowed(username, entity.id):
                identifier = self._normalize_channel(username or entity.id)
                if identifier in self.channel_blacklist:
                    skipped_blacklist += 1
                    logger.debug(f"Канал исключён blacklist: @{username} - {title}")
                else:
                    logger.debug(f"Канал не входит в whitelist: @{username} - {title}")
                continue

            # QA-3: Добавляем в БД неблокирующим способом
            await asyncio.to_thread(self.db.add_channel, username, title)
            if entity.id in self._channel_id_set:
                skipped_duplicates += 1
                logger.debug(f"Канал уже добавлен ранее: @{username}")
                continue

            self.channel_ids.append(entity.id)
            self._channel_id_set.add(entity.id)
            channel_count += 1
            logger.info(f"Канал добавлен (manual): @{username} - {title}")

        logger.info(f"Загружено {channel_count} каналов (manual)")
        if skipped_blacklist:
            logger.info(f"Пропущено каналов по blacklist: {skipped_blacklist}")
        if skipped_duplicates:
            logger.info(f"Пропущено дубликатов: {skipped_duplicates}")
        if skipped_errors:
            logger.info(f"Пропущено каналов из-за ошибок: {skipped_errors}")

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

            # Санитизация текста сообщения
            text = sanitize_text(message.text, max_length=self.MAX_MESSAGE_SIZE)

            # Проверка безопасности перед сохранением
            if not is_safe_for_storage(text):
                logger.warning(
                    "Сообщение содержит опасный контент. Канал: %s",
                    event.chat_id,
                )
                return

            # Security: Дополнительная проверка размера после санитизации
            if len(text) < 10:  # Слишком короткое после очистки
                logger.debug("Сообщение слишком короткое после санитизации")
                return

            # Фильтры: для постов с медиа снижаем порог до 10 символов
            has_media = bool(message.media)
            current_min_length = 10 if has_media else self.min_message_length
            if len(text) < current_min_length:
                logger.debug(
                    "Message dropped: text too short (%d chars). Media: %s",
                    len(text), has_media,
                )
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
            username = sanitize_channel_name(chat.username or str(chat.id))
            channel_title = sanitize_channel_name(chat.title or username)

            # QA-3: Получаем channel_id из БД неблокирующим способом
            channel_id = await asyncio.to_thread(self.db.get_channel_id, username)
            if not channel_id:
                # Если канала нет в БД (странно), добавляем
                channel_id = await asyncio.to_thread(self.db.add_channel, username, channel_title)

            # QA-3: Сохраняем сообщение неблокирующим способом
            has_media = message.media is not None
            saved_id = await asyncio.to_thread(
                self.db.save_message,
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


# QA-7: Функция run_listener удалена как мёртвый код (не используется, битая сигнатура)
