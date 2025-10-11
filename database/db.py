"""Работа с базой данных SQLite"""
import sqlite3
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np

from utils.logger import setup_logger

logger = setup_logger(__name__)


class Database:
    """Класс для работы с SQLite базой данных"""

    def __init__(self, db_path: str):
        """
        Инициализация базы данных

        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.init_db()

    def connect(self):
        """Подключение к базе данных"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Для доступа по именам столбцов
        return self.conn

    def init_db(self):
        """Создание таблиц если их нет"""
        conn = self.connect()
        cursor = conn.cursor()

        # Таблица каналов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                title TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица сырых сообщений
        cursor.execute('''
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
        ''')

        # Индексы для raw_messages
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_processed
            ON raw_messages(processed, date)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_date
            ON raw_messages(date)
        ''')

        # Таблица опубликованных постов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS published (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                embedding BLOB,
                source_message_id INTEGER,
                source_channel_id INTEGER,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_message_id) REFERENCES raw_messages(id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_published_date
            ON published(published_at)
        ''')

        # Таблица конфигурации
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        conn.commit()
        logger.info(f"База данных инициализирована: {self.db_path}")

    # ====== РАБОТА С КАНАЛАМИ ======

    def add_channel(self, username: str, title: str = "") -> int:
        """
        Добавить канал в базу

        Args:
            username: Username канала (с @ или без)
            title: Название канала

        Returns:
            ID добавленного канала
        """
        username = username.lstrip('@')
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                'INSERT INTO channels (username, title) VALUES (?, ?)',
                (username, title)
            )
            self.conn.commit()
            logger.info(f"Добавлен канал: @{username}")
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Канал уже существует
            cursor.execute('SELECT id FROM channels WHERE username = ?', (username,))
            return cursor.fetchone()[0]

    def get_channel_id(self, username: str) -> Optional[int]:
        """Получить ID канала по username"""
        username = username.lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM channels WHERE username = ?', (username,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_active_channels(self) -> List[Dict]:
        """Получить список активных каналов"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM channels WHERE is_active = 1')
        return [dict(row) for row in cursor.fetchall()]

    # ====== РАБОТА С СООБЩЕНИЯМИ ======

    def save_message(self, channel_id: int, message_id: int, text: str,
                    date: datetime, has_media: bool = False) -> Optional[int]:
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
        cursor = self.conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO raw_messages
                (channel_id, message_id, text, date, has_media)
                VALUES (?, ?, ?, ?, ?)
            ''', (channel_id, message_id, text, date, has_media))
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Сообщение уже существует
            return None

    def get_unprocessed_messages(self, hours: int = 24) -> List[Dict]:
        """
        Получить необработанные сообщения за последние N часов

        Args:
            hours: Количество часов назад

        Returns:
            Список сообщений
        """
        cursor = self.conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=hours)

        cursor.execute('''
            SELECT m.*, c.username as channel_username
            FROM raw_messages m
            JOIN channels c ON m.channel_id = c.id
            WHERE m.processed = 0
              AND m.date > ?
            ORDER BY m.date DESC
        ''', (cutoff_time,))

        return [dict(row) for row in cursor.fetchall()]

    def mark_as_processed(self, message_id: int, is_duplicate: bool = False,
                         gemini_score: Optional[int] = None):
        """Пометить сообщение как обработанное"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE raw_messages
            SET processed = 1, is_duplicate = ?, gemini_score = ?
            WHERE id = ?
        ''', (is_duplicate, gemini_score, message_id))
        self.conn.commit()

    # ====== РАБОТА С ОПУБЛИКОВАННЫМИ ПОСТАМИ ======

    def save_published(self, text: str, embedding: np.ndarray,
                      source_message_id: int, source_channel_id: int) -> int:
        """
        Сохранить опубликованный пост

        Args:
            text: Текст поста
            embedding: Embedding для проверки дубликатов
            source_message_id: ID исходного сообщения
            source_channel_id: ID канала-источника

        Returns:
            ID записи
        """
        cursor = self.conn.cursor()
        # Сериализуем embedding в bytes
        embedding_bytes = pickle.dumps(embedding)

        cursor.execute('''
            INSERT INTO published
            (text, embedding, source_message_id, source_channel_id)
            VALUES (?, ?, ?, ?)
        ''', (text, embedding_bytes, source_message_id, source_channel_id))
        self.conn.commit()
        return cursor.lastrowid

    def get_published_embeddings(self, days: int = 60) -> List[Tuple[int, np.ndarray]]:
        """
        Получить embeddings опубликованных постов за последние N дней

        Args:
            days: Количество дней назад

        Returns:
            Список (id, embedding)
        """
        cursor = self.conn.cursor()
        cutoff_time = datetime.now() - timedelta(days=days)

        cursor.execute('''
            SELECT id, embedding FROM published
            WHERE published_at > ? AND embedding IS NOT NULL
        ''', (cutoff_time,))

        results = []
        for row in cursor.fetchall():
            embedding = pickle.loads(row[1])
            results.append((row[0], embedding))

        return results

    # ====== ОЧИСТКА ======

    def cleanup_old_data(self, raw_days: int = 14, published_days: int = 60):
        """
        Удалить старые данные

        Args:
            raw_days: Удалить raw_messages старше N дней
            published_days: Удалить published старше N дней
        """
        cursor = self.conn.cursor()

        raw_cutoff = datetime.now() - timedelta(days=raw_days)
        published_cutoff = datetime.now() - timedelta(days=published_days)

        # Удаляем старые сырые сообщения
        cursor.execute('DELETE FROM raw_messages WHERE date < ?', (raw_cutoff,))
        raw_deleted = cursor.rowcount

        # Удаляем старые опубликованные посты
        cursor.execute('DELETE FROM published WHERE published_at < ?', (published_cutoff,))
        published_deleted = cursor.rowcount

        # VACUUM для сжатия БД
        cursor.execute('VACUUM')

        self.conn.commit()
        logger.info(f"Очистка БД: удалено {raw_deleted} сырых сообщений, "
                   f"{published_deleted} опубликованных постов")

    def get_stats(self) -> Dict:
        """Получить статистику по базе"""
        cursor = self.conn.cursor()

        stats = {}

        cursor.execute('SELECT COUNT(*) FROM channels WHERE is_active = 1')
        stats['active_channels'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM raw_messages WHERE processed = 0')
        stats['unprocessed_messages'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM raw_messages')
        stats['total_messages'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM published')
        stats['total_published'] = cursor.fetchone()[0]

        return stats

    def get_today_stats(self) -> Dict:
        """Получить статистику за сегодня"""
        cursor = self.conn.cursor()
        stats = {}

        # Сообщения, собранные сегодня
        cursor.execute('''
            SELECT COUNT(*) FROM raw_messages
            WHERE date(date) = date('now')
        ''')
        stats['messages_today'] = cursor.fetchone()[0]

        # Обработанные сегодня (created_at - когда добавлено в БД, дата обработки)
        cursor.execute('''
            SELECT COUNT(*) FROM raw_messages
            WHERE date(created_at) = date('now') AND processed = 1
        ''')
        stats['processed_today'] = cursor.fetchone()[0]

        # Необработанные
        cursor.execute('''
            SELECT COUNT(*) FROM raw_messages
            WHERE processed = 0
        ''')
        stats['unprocessed'] = cursor.fetchone()[0]

        # Опубликованные сегодня
        cursor.execute('''
            SELECT COUNT(*) FROM published
            WHERE date(published_at) = date('now')
        ''')
        stats['published_today'] = cursor.fetchone()[0]

        # Активные каналы
        cursor.execute('SELECT COUNT(*) FROM channels WHERE is_active = 1')
        stats['active_channels'] = cursor.fetchone()[0]

        return stats

    def close(self):
        """Закрыть соединение с БД"""
        if self.conn:
            self.conn.close()
            logger.info("Соединение с БД закрыто")
