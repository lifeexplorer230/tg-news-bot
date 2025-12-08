"""Работа с базой данных SQLite"""

from __future__ import annotations

import io
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from utils.logger import setup_logger
from utils.timezone import get_timezone, now_in_timezone, now_msk, now_utc, to_utc
from database.connection_pool import ConnectionPool

logger = setup_logger(__name__)


def retry_on_locked(func):
    """Декоратор для повторных попыток при блокировке БД"""

    def wrapper(self, *args, **kwargs):
        max_retries = getattr(self, "_retry_max_attempts", 5)
        base_delay = getattr(self, "_retry_base_delay", 0.5)
        multiplier = getattr(self, "_retry_backoff_multiplier", 1.0)

        for attempt in range(max_retries):
            try:
                return func(self, *args, **kwargs)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    delay = base_delay * (attempt + 1) * multiplier
                    logger.warning(
                        "БД заблокирована, попытка %s/%s, повтор через %.2f c",
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise
        return None

    return wrapper


class Database:
    """Класс для работы с SQLite базой данных"""

    def __init__(
        self,
        db_path: str,
        *,
        timeout: float = 30.0,
        busy_timeout_ms: int = 30000,
        retry_max_attempts: int = 5,
        retry_base_delay: float = 0.5,
        retry_backoff_multiplier: float = 1.0,
    ):
        """
        Инициализация базы данных

        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        self._timeout = float(timeout)
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._retry_max_attempts = max(1, int(retry_max_attempts))
        self._retry_base_delay = max(0.0, float(retry_base_delay))
        self._retry_backoff_multiplier = max(0.0, float(retry_backoff_multiplier)) or 1.0
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Используем connection pool вместо одного соединения
        self._pool = ConnectionPool(
            db_path,
            max_connections=5,  # 5 соединений в пуле
            timeout=timeout,
            busy_timeout_ms=busy_timeout_ms
        )

        self.conn: sqlite3.Connection | None = None  # Для обратной совместимости
        self._lock = threading.Lock()  # Thread safety для write operations
        self._closed = False  # Track if connection was explicitly closed
        self.init_db()

    def connect(self):
        """Подключение к базе данных (для обратной совместимости)"""
        # Для совместимости с существующим кодом
        # В новом коде лучше использовать get_connection()
        if self.conn is None:
            self.conn = self._pool._create_connection()
        return self.conn

    def get_connection(self):
        """Получить соединение из пула (рекомендуемый метод)"""
        return self._pool.get_connection()

    def init_db(self):
        """Создание таблиц если их нет"""
        conn = self.connect()
        cursor = conn.cursor()

        # Таблица каналов
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                title TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Таблица сырых сообщений
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                date TIMESTAMP NOT NULL,
                has_media BOOLEAN DEFAULT 0,
                processed BOOLEAN DEFAULT 0,
                is_duplicate BOOLEAN DEFAULT 0,
                gemini_score INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id),
                UNIQUE(channel_id, message_id)
            )
        """
        )

        # Добавляем новое поле если его нет
        cursor.execute("PRAGMA table_info(raw_messages)")
        columns = [col[1] for col in cursor.fetchall()]
        if "rejection_reason" not in columns:
            cursor.execute("ALTER TABLE raw_messages ADD COLUMN rejection_reason TEXT")
            logger.info("Добавлено поле rejection_reason в raw_messages")

        # Индексы для raw_messages
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed
            ON raw_messages(processed, date)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_date
            ON raw_messages(date)
        """
        )

        # Таблица опубликованных постов
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS published (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                embedding BLOB,
                source_message_id INTEGER,
                source_channel_id INTEGER,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_message_id) REFERENCES raw_messages(id)
            )
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_published_date
            ON published(published_at)
        """
        )

        # Миграция: удаляем дубликаты и добавляем UNIQUE constraint на source_message_id
        # Это предотвращает публикацию одного сообщения дважды
        self._migrate_published_unique_constraint(cursor)

        # Таблица конфигурации
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        conn.commit()
        logger.info(f"База данных инициализирована: {self.db_path}")

    def _migrate_published_unique_constraint(self, cursor: sqlite3.Cursor):
        """
        Миграция: добавить UNIQUE constraint на (source_message_id, source_channel_id)

        Это предотвращает публикацию одного сообщения дважды.
        Миграция идемпотентна - можно запускать многократно.
        """
        # Проверяем, существует ли уже индекс
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_published_source_unique'"
        )
        if cursor.fetchone():
            # Индекс уже существует, миграция не нужна
            return

        logger.info("🔄 Запуск миграции: добавление UNIQUE constraint на published")

        # Подсчитываем дубликаты перед удалением
        cursor.execute("""
            SELECT COUNT(*) FROM published
            WHERE id NOT IN (
                SELECT MAX(id) FROM published
                WHERE source_message_id IS NOT NULL
                GROUP BY source_message_id, source_channel_id
            )
            AND source_message_id IS NOT NULL
        """)
        duplicate_count = cursor.fetchone()[0]

        if duplicate_count > 0:
            logger.warning(f"⚠️ Найдено {duplicate_count} дубликатов в published, удаляем...")

            # Удаляем дубликаты, оставляя только последнюю запись для каждой пары
            cursor.execute("""
                DELETE FROM published
                WHERE id NOT IN (
                    SELECT MAX(id) FROM published
                    WHERE source_message_id IS NOT NULL
                    GROUP BY source_message_id, source_channel_id
                )
                AND source_message_id IS NOT NULL
            """)
            logger.info(f"✅ Удалено {duplicate_count} дубликатов")

        # Создаём уникальный индекс
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_published_source_unique
            ON published(source_message_id, source_channel_id)
            WHERE source_message_id IS NOT NULL
        """)
        logger.info("✅ Создан UNIQUE индекс idx_published_source_unique")

    # ====== РАБОТА С КАНАЛАМИ ======

    @retry_on_locked
    def add_channel(self, username: str, title: str = "") -> int:
        """
        Добавить канал в базу

        Args:
            username: Username канала (с @ или без)
            title: Название канала

        Returns:
            ID добавленного канала
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            username = username.lstrip("@")
            cursor = self.conn.cursor()

            try:
                cursor.execute(
                    "INSERT INTO channels (username, title) VALUES (?, ?)", (username, title)
                )
                self.conn.commit()
                logger.info(f"Добавлен канал: @{username}")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Канал уже существует
                cursor.execute("SELECT id FROM channels WHERE username = ?", (username,))
                return cursor.fetchone()[0]

    def get_channel_id(self, username: str) -> int | None:
        """Получить ID канала по username"""
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            username = username.lstrip("@")
            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM channels WHERE username = ?", (username,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_active_channels(self) -> list[dict]:
        """Получить список активных каналов"""
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM channels WHERE is_active = 1")
            return [dict(row) for row in cursor.fetchall()]

    # ====== РАБОТА С СООБЩЕНИЯМИ ======

    @retry_on_locked
    def save_message(
        self, channel_id: int, message_id: int, text: str, date: datetime, has_media: bool = False
    ) -> int | None:
        """
        Сохранить сообщение из канала

        Args:
            channel_id: ID канала
            message_id: ID сообщения в Telegram
            text: Текст сообщения
            date: Дата сообщения
            has_media: Есть ли медиа

        Returns:
            ID записи или None если уже существует
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO raw_messages
                    (channel_id, message_id, text, date, has_media)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (channel_id, message_id, text, date, has_media),
                )
                self.conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Сообщение уже существует
                return None

    def get_unprocessed_messages(self, hours: int = 24) -> list[dict]:
        """
        Получить необработанные сообщения за последние N часов

        Args:
            hours: Количество часов назад

        Returns:
            Список сообщений
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            # ИСПРАВЛЕНИЕ: используем UTC для сравнения, т.к. message.date хранится в UTC
            cutoff_time = now_utc() - timedelta(hours=hours)

            cursor.execute(
                """
                SELECT m.*, c.username as channel_username
                FROM raw_messages m
                JOIN channels c ON m.channel_id = c.id
                WHERE m.processed = 0
                  AND m.date > ?
                ORDER BY m.date DESC
            """,
                (cutoff_time,),
            )

            return [dict(row) for row in cursor.fetchall()]

    @retry_on_locked
    def mark_as_processed(
        self,
        message_id: int,
        is_duplicate: bool = False,
        gemini_score: int | None = None,
        rejection_reason: str | None = None,
    ):
        """
        Пометить сообщение как обработанное

        Args:
            message_id: ID сообщения
            is_duplicate: Является ли сообщение дубликатом
            gemini_score: Оценка Gemini (для публикаций)
            rejection_reason: Причина отклонения (если не опубликовано)
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE raw_messages
                SET processed = 1,
                    is_duplicate = ?,
                    gemini_score = ?,
                    rejection_reason = ?
                WHERE id = ?
            """,
                (is_duplicate, gemini_score, rejection_reason, message_id),
            )
            self.conn.commit()

    @retry_on_locked
    def mark_as_processed_batch(self, updates: list[dict]):
        """
        Батч-пометка сообщений как обработанные за одну транзакцию (Sprint 6.1)

        Оптимизация: вместо N коммитов делаем 1 коммит на весь батч.
        Решает проблему избыточных транзакций SQLite.

        Args:
            updates: Список словарей с полями:
                - message_id: int (обязательно)
                - is_duplicate: bool (по умолчанию False)
                - gemini_score: int | None (по умолчанию None)
                - rejection_reason: str | None (по умолчанию None)

        Example:
            updates = [
                {'message_id': 1, 'rejection_reason': 'spam'},
                {'message_id': 2, 'is_duplicate': True},
                {'message_id': 3, 'gemini_score': 8},
            ]
            db.mark_as_processed_batch(updates)
        """
        if not updates:
            return

        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()

            # Подготавливаем данные для executemany
            # Порядок: (is_duplicate, gemini_score, rejection_reason, message_id)
            batch_data = [
                (
                    update.get('is_duplicate', False),
                    update.get('gemini_score'),
                    update.get('rejection_reason'),
                    update['message_id']  # message_id обязателен
                )
                for update in updates
            ]

            cursor.executemany(
                """
                UPDATE raw_messages
                SET processed = 1,
                    is_duplicate = ?,
                    gemini_score = ?,
                    rejection_reason = ?
                WHERE id = ?
            """,
                batch_data
            )

            # ОДИН commit на весь батч!
            self.conn.commit()
            logger.debug(f"Batch processed {len(updates)} messages")

    # ====== РАБОТА С ОПУБЛИКОВАННЫМИ ПОСТАМИ ======

    @retry_on_locked
    def save_published(
        self, text: str, embedding: np.ndarray, source_message_id: int, source_channel_id: int
    ) -> int:
        """
        Сохранить опубликованный пост

        Использует INSERT OR IGNORE для предотвращения дублирования
        (защита на уровне БД через UNIQUE индекс на source_message_id, source_channel_id)

        Args:
            text: Текст поста
            embedding: Embedding для проверки дубликатов
            source_message_id: ID исходного сообщения
            source_channel_id: ID канала-источника

        Returns:
            ID записи или -1 если запись уже существует (дубликат)
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            # Сериализуем embedding в bytes через numpy (безопасно, без pickle)
            buffer = io.BytesIO()
            np.save(buffer, embedding, allow_pickle=False)
            embedding_bytes = buffer.getvalue()

            cursor.execute(
                """
                INSERT OR IGNORE INTO published
                (text, embedding, source_message_id, source_channel_id)
                VALUES (?, ?, ?, ?)
            """,
                (text, embedding_bytes, source_message_id, source_channel_id),
            )
            self.conn.commit()

            if cursor.rowcount == 0:
                logger.warning(
                    f"⚠️ Дубликат пропущен в save_published: "
                    f"source_message_id={source_message_id}, source_channel_id={source_channel_id}"
                )
                return -1
            return cursor.lastrowid

    def get_published_embeddings(self, days: int = 60) -> list[tuple[int, np.ndarray]]:
        """
        Получить embeddings опубликованных постов за последние N дней

        Args:
            days: Количество дней назад

        Returns:
            Список (id, embedding)
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            # ИСПРАВЛЕНИЕ: используем UTC, т.к. CURRENT_TIMESTAMP в SQLite = UTC
            cutoff_time = now_utc() - timedelta(days=days)

            cursor.execute(
                """
                SELECT id, embedding FROM published
                WHERE published_at > ? AND embedding IS NOT NULL
            """,
                (cutoff_time,),
            )

            results = []
            for row in cursor.fetchall():
                # Десериализуем через numpy (безопасно, без pickle)
                buffer = io.BytesIO(row[1])
                embedding = np.load(buffer, allow_pickle=False)
                results.append((row[0], embedding))

            return results

    def check_duplicate(self, embedding: np.ndarray, threshold: float = 0.85) -> bool:
        """
        Проверить является ли текст дубликатом опубликованного

        Args:
            embedding: Embedding текста для проверки
            threshold: Порог схожести (0.0 - 1.0)

        Returns:
            True если найден дубликат
        """
        # Блокировка внутри get_published_embeddings
        published_embeddings = self.get_published_embeddings(days=60)

        if not published_embeddings:
            return False

        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm == 0:
            logger.warning("Получен embedding с нулевой нормой при проверке дубликатов")
            return False

        for post_id, published_embedding in published_embeddings:
            published_norm = np.linalg.norm(published_embedding)
            if published_norm == 0:
                logger.debug(
                    f"Пропущен опубликованный пост {post_id} из-за нулевой нормы embedding"
                )
                continue

            similarity = np.dot(embedding, published_embedding) / (embedding_norm * published_norm)

            if similarity >= threshold:
                logger.debug(f"Найден дубликат: post_id={post_id}, similarity={similarity:.3f}")
                return True

        return False

    # ====== ОЧИСТКА ======

    @retry_on_locked
    def cleanup_old_data(self, raw_days: int = 14, published_days: int = 60):
        """
        Удалить старые данные

        Args:
            raw_days: Удалить raw_messages старше N дней
            published_days: Удалить published старше N дней
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()

            # ИСПРАВЛЕНИЕ: используем UTC для обеих таблиц (даты хранятся в UTC)
            raw_cutoff = now_utc() - timedelta(days=raw_days)
            published_cutoff = now_utc() - timedelta(days=published_days)

            # Удаляем старые сырые сообщения
            cursor.execute("DELETE FROM raw_messages WHERE date < ?", (raw_cutoff,))
            raw_deleted = cursor.rowcount

            # Удаляем старые опубликованные посты
            cursor.execute("DELETE FROM published WHERE published_at < ?", (published_cutoff,))
            published_deleted = cursor.rowcount

            # Коммитим транзакцию перед VACUUM
            self.conn.commit()

            # VACUUM для сжатия БД (должен быть вне транзакции)
            cursor.execute("VACUUM")
            logger.info(
                f"Очистка БД: удалено {raw_deleted} сырых сообщений, "
                f"{published_deleted} опубликованных постов"
            )

            return {"raw": raw_deleted, "published": published_deleted}

    def get_stats(self) -> dict:
        """Получить статистику по базе"""
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()

            stats = {}

            cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
            stats["active_channels"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM raw_messages WHERE processed = 0")
            stats["unprocessed_messages"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            stats["total_messages"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM published")
            stats["total_published"] = cursor.fetchone()[0]

            return stats

    def get_today_stats(self, timezone_name: str | None = None) -> dict:
        """
        Получить статистику за сегодня

        Args:
            timezone_name: Имя timezone (например, 'Europe/Moscow').
                          Если None, используется UTC.

        Returns:
            dict со статистикой
        """
        with self._lock:  # Sprint 6.2: Thread-safe доступ
            cursor = self.conn.cursor()
            stats = {}

            # Определяем границы "сегодня" в нужной timezone
            if timezone_name:
                tz = get_timezone(timezone_name)
                now = now_in_timezone(tz)
                # Начало дня в локальной timezone
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                # Конец дня в локальной timezone
                end_of_day = start_of_day + timedelta(days=1)
                # Конвертируем в UTC для запросов к БД
                start_utc = to_utc(start_of_day)
                end_utc = to_utc(end_of_day)
            else:
                # Fallback: используем UTC
                from datetime import UTC

                now_utc = datetime.now(UTC)
                start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                end_utc = start_utc + timedelta(days=1)

            # Форматируем для SQL (SQLite хранит timestamps как строки или числа)
            start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

            # Сообщения, собранные сегодня
            cursor.execute(
                """
                SELECT COUNT(*) FROM raw_messages
                WHERE date >= ? AND date < ?
            """,
                (start_str, end_str),
            )
            stats["messages_today"] = cursor.fetchone()[0]

            # Обработанные сегодня (created_at - когда добавлено в БД, дата обработки)
            cursor.execute(
                """
                SELECT COUNT(*) FROM raw_messages
                WHERE created_at >= ? AND created_at < ? AND processed = 1
            """,
                (start_str, end_str),
            )
            stats["processed_today"] = cursor.fetchone()[0]

            # Необработанные
            cursor.execute(
                """
                SELECT COUNT(*) FROM raw_messages
                WHERE processed = 0
            """
            )
            stats["unprocessed"] = cursor.fetchone()[0]

            # Опубликованные сегодня
            cursor.execute(
                """
                SELECT COUNT(*) FROM published
                WHERE published_at >= ? AND published_at < ?
            """,
                (start_str, end_str),
            )
            stats["published_today"] = cursor.fetchone()[0]

            # Активные каналы
            cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
            stats["active_channels"] = cursor.fetchone()[0]

            # Всего сообщений
            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            stats["total_messages"] = cursor.fetchone()[0]

            # Всего опубликованных
            cursor.execute("SELECT COUNT(*) FROM published")
            stats["total_published"] = cursor.fetchone()[0]

            return stats

    def close(self):
        """Закрыть соединение с БД (idempotent, thread-safe)"""
        with self._lock:
            if self._closed:
                return  # Already closed
            if self.conn:
                try:
                    self.conn.close()
                    logger.info("Соединение с БД закрыто")
                except Exception as e:
                    logger.error(f"Ошибка при закрытии соединения: {e}")
                finally:
                    self.conn = None
                    self._closed = True

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.close()
        return False

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.close()
        except Exception:
            pass  # Suppress errors during cleanup
