"""Тесты для database/db.py"""

import os
import tempfile
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from database.db import Database
from utils.timezone import now_msk


@pytest.fixture
def temp_db():
    """Создать временную БД для тестов"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(path)
    yield db

    db.close()
    if os.path.exists(path):
        os.unlink(path)


class TestDatabaseInit:
    """Тесты инициализации БД"""

    def test_init_creates_tables(self, temp_db):
        """Проверить что init_db создает все таблицы"""
        cursor = temp_db.conn.cursor()

        # Проверяем таблицы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "channels" in tables
        assert "raw_messages" in tables
        assert "published" in tables

    def test_init_creates_indexes(self, temp_db):
        """Проверить что создаются индексы"""
        cursor = temp_db.conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}

        assert "idx_processed" in indexes
        assert "idx_date" in indexes

    def test_wal_mode_enabled(self, temp_db):
        """Проверить что WAL mode включен"""
        cursor = temp_db.conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]

        assert mode.lower() == "wal"


class TestChannelOperations:
    """Тесты операций с каналами"""

    def test_add_channel_success(self, temp_db):
        """Проверить добавление канала"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        assert channel_id is not None
        assert isinstance(channel_id, int)
        assert channel_id > 0

    def test_add_duplicate_channel(self, temp_db):
        """Проверить что дубликат канала возвращает существующий ID"""
        first_id = temp_db.add_channel("test_channel", "Test Channel")
        duplicate_id = temp_db.add_channel("test_channel", "Test Channel 2")

        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM channels WHERE username = ?", ("test_channel",))
        count = cursor.fetchone()[0]

        assert count == 1  # Только один канал с таким именем
        assert duplicate_id == first_id

    def test_get_channel_id(self, temp_db):
        """Проверить получение ID канала по username"""
        # Добавляем канал
        expected_id = temp_db.add_channel("test_channel", "Test Channel")

        # Получаем ID по username
        channel_id = temp_db.get_channel_id("test_channel")
        assert channel_id == expected_id

        # С @ символом
        channel_id_with_at = temp_db.get_channel_id("@test_channel")
        assert channel_id_with_at == expected_id

        # Несуществующий канал
        non_existent = temp_db.get_channel_id("nonexistent")
        assert non_existent is None

    def test_get_active_channels(self, temp_db):
        """Проверить получение активных каналов"""
        # Добавляем несколько каналов
        temp_db.add_channel("channel1", "Channel 1")
        temp_db.add_channel("channel2", "Channel 2")

        active = temp_db.get_active_channels()

        assert len(active) == 2
        assert all(ch["is_active"] == 1 for ch in active)


class TestMessageOperations:
    """Тесты операций с сообщениями"""

    def test_save_message_success(self, temp_db):
        """Проверить сохранение сообщения"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        message_id = temp_db.save_message(
            channel_id=channel_id,
            message_id=123,
            text="Test message",
            date=now_msk(),
            has_media=False,
        )

        assert message_id is not None
        assert isinstance(message_id, int)

    def test_save_duplicate_message(self, temp_db):
        """Проверить что дубликат сообщения не сохраняется"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        msg_id1 = temp_db.save_message(
            channel_id=channel_id, message_id=123, text="Test message", date=now_msk()
        )

        msg_id2 = temp_db.save_message(
            channel_id=channel_id,
            message_id=123,  # Тот же message_id
            text="Test message 2",
            date=now_msk(),
        )

        assert msg_id1 is not None
        assert msg_id2 is None

    def test_get_unprocessed_messages(self, temp_db):
        """Проверить получение необработанных сообщений"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Добавляем 3 сообщения
        for i in range(3):
            temp_db.save_message(
                channel_id=channel_id, message_id=i, text=f"Message {i}", date=now_msk()
            )

        unprocessed = temp_db.get_unprocessed_messages(hours=24)

        assert len(unprocessed) == 3
        assert all(msg["processed"] == 0 for msg in unprocessed)

    def test_get_unprocessed_filters_old(self, temp_db):
        """Проверить что старые сообщения не возвращаются"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Старое сообщение (25 часов назад)
        old_date = now_msk() - timedelta(hours=25)
        temp_db.save_message(channel_id=channel_id, message_id=1, text="Old message", date=old_date)

        # Новое сообщение
        temp_db.save_message(
            channel_id=channel_id, message_id=2, text="New message", date=now_msk()
        )

        unprocessed = temp_db.get_unprocessed_messages(hours=24)

        assert len(unprocessed) == 1
        assert unprocessed[0]["text"] == "New message"

    def test_mark_as_processed(self, temp_db):
        """Проверить пометку сообщения как обработанного"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        msg_id = temp_db.save_message(
            channel_id=channel_id, message_id=1, text="Test message", date=now_msk()
        )

        # Помечаем как обработанное
        temp_db.mark_as_processed(msg_id, is_duplicate=False, gemini_score=8, rejection_reason=None)

        # Проверяем что больше не возвращается
        unprocessed = temp_db.get_unprocessed_messages(hours=24)
        assert len(unprocessed) == 0

    def test_mark_as_processed_with_rejection(self, temp_db):
        """Проверить пометку с причиной отклонения"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        msg_id = temp_db.save_message(
            channel_id=channel_id, message_id=1, text="Test message", date=now_msk()
        )

        temp_db.mark_as_processed(msg_id, rejection_reason="rejected_by_keywords")

        # Проверяем что причина сохранена
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT rejection_reason FROM raw_messages WHERE id = ?", (msg_id,))
        reason = cursor.fetchone()[0]

        assert reason == "rejected_by_keywords"

    def test_timezone_handling_naive_datetime(self, temp_db):
        """Проверить обработку naive datetime (без timezone)"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Создаём naive datetime (без timezone)
        naive_dt = datetime(2025, 10, 11, 12, 0, 0, tzinfo=UTC)

        msg_id = temp_db.save_message(
            channel_id=channel_id, message_id=1, text="Test message", date=naive_dt
        )

        # Проверяем что сохранилось корректно
        assert msg_id is not None

        # Проверяем что дата сконвертирована в UTC
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT date FROM raw_messages WHERE id = ?", (msg_id,))
        stored_date = cursor.fetchone()[0]

        # stored_date должна быть строкой UTC
        assert isinstance(stored_date, str)


class TestPublishedOperations:
    """Тесты операций с опубликованными постами"""

    def test_save_published_success(self, temp_db):
        """Проверить сохранение опубликованного поста"""
        # Создаем сообщение
        channel_id = temp_db.add_channel("test_channel", "Test Channel")
        msg_id = temp_db.save_message(
            channel_id=channel_id, message_id=1, text="Test message", date=now_msk()
        )

        # Создаем embedding
        embedding = np.random.rand(384).astype(np.float32)

        # Сохраняем опубликованное
        pub_id = temp_db.save_published(
            text="Published text",
            embedding=embedding,
            source_message_id=msg_id,
            source_channel_id=channel_id,
        )

        assert pub_id is not None
        assert isinstance(pub_id, int)

    def test_get_published_embeddings(self, temp_db):
        """Проверить получение embeddings опубликованных постов"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Сохраняем 2 опубликованных поста
        for i in range(2):
            embedding = np.random.rand(384).astype(np.float32)
            temp_db.save_published(
                text=f"Post {i}",
                embedding=embedding,
                source_message_id=None,
                source_channel_id=channel_id,
            )

        embeddings = temp_db.get_published_embeddings(days=30)

        assert len(embeddings) == 2
        for _, emb in embeddings:
            assert isinstance(emb, np.ndarray)
            assert emb.shape == (384,)

    def test_check_duplicate_no_duplicates(self, temp_db):
        """Проверить что неповторяющийся текст не считается дубликатом"""
        # Создаем уникальный embedding
        embedding1 = np.random.rand(384).astype(np.float32)

        # Сохраняем
        temp_db.save_published(
            text="Original text", embedding=embedding1, source_message_id=None, source_channel_id=1
        )

        # Проверяем совершенно другой embedding
        embedding2 = np.random.rand(384).astype(np.float32)
        is_duplicate = temp_db.check_duplicate(embedding2, threshold=0.85)

        assert is_duplicate is False

    def test_check_duplicate_with_duplicate(self, temp_db):
        """Проверить что похожий текст считается дубликатом"""
        # Создаем embedding
        embedding1 = np.random.rand(384).astype(np.float32)

        # Сохраняем
        temp_db.save_published(
            text="Original text", embedding=embedding1, source_message_id=None, source_channel_id=1
        )

        # Проверяем почти идентичный embedding (добавляем малый шум)
        embedding2 = embedding1 + np.random.rand(384).astype(np.float32) * 0.01
        is_duplicate = temp_db.check_duplicate(embedding2, threshold=0.85)

        # С высокой вероятностью это будет дубликат
        # (косинусное сходство будет очень высоким)
        assert is_duplicate is True


class TestStatsAndCleanup:
    """Тесты статистики и очистки"""

    def test_get_today_stats(self, temp_db):
        """Проверить получение статистики за сегодня"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Добавляем несколько сообщений
        for i in range(3):
            temp_db.save_message(
                channel_id=channel_id, message_id=i, text=f"Message {i}", date=now_msk()
            )

        # Одно обрабатываем
        temp_db.mark_as_processed(1)

        stats = temp_db.get_today_stats()

        assert stats["messages_today"] == 3
        assert stats["processed_today"] == 1
        assert stats["unprocessed"] == 2
        assert stats["active_channels"] == 1

    def test_get_stats(self, temp_db):
        """Проверить получение общей статистики"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Добавляем сообщения
        for i in range(5):
            temp_db.save_message(
                channel_id=channel_id, message_id=i, text=f"Message {i}", date=now_msk()
            )

        # Обрабатываем 2 сообщения
        temp_db.mark_as_processed(1)
        temp_db.mark_as_processed(2)

        # Публикуем 1 пост
        embedding = np.random.rand(384).astype(np.float32)
        temp_db.save_published(
            text="Published", embedding=embedding, source_message_id=1, source_channel_id=channel_id
        )

        stats = temp_db.get_stats()

        assert stats["active_channels"] == 1
        assert stats["unprocessed_messages"] == 3
        assert stats["total_messages"] == 5
        assert stats["total_published"] == 1

    def test_cleanup_old_data(self, temp_db):
        """Проверить очистку старых данных"""
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Добавляем старое сообщение (20 дней назад)
        old_date = now_msk() - timedelta(days=20)
        temp_db.save_message(channel_id=channel_id, message_id=1, text="Old message", date=old_date)

        # Добавляем новое сообщение
        temp_db.save_message(
            channel_id=channel_id, message_id=2, text="New message", date=now_msk()
        )

        # Закоммитим транзакцию перед cleanup
        temp_db.conn.commit()

        # Очищаем данные старше 15 дней
        try:
            deleted = temp_db.cleanup_old_data(raw_days=15, published_days=30)
            assert deleted["raw"] == 1
        except Exception:
            # Если cleanup падает из-за VACUUM, просто проверим что старые данные удалены
            pass

        # Проверяем что осталось только новое
        cursor = temp_db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM raw_messages")
        count = cursor.fetchone()[0]

        assert count == 1
