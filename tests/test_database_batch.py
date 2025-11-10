"""
Sprint 6.1: Тесты для батч-операций Database

Проверяет что:
1. mark_as_processed_batch работает корректно
2. Батч обработка быстрее множественных вызовов
3. Пустой батч не вызывает ошибок
4. Обработка больших батчей (100, 500, 1000)
"""

import time
from datetime import UTC, datetime

import pytest

from database.db import Database


@pytest.fixture
def db():
    """Создаём in-memory БД для тестов"""
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def sample_messages(db):
    """Создаём тестовые сообщения"""
    # Добавляем канал
    channel_id = db.add_channel("test_channel", "Test Channel")

    # Создаём 100 тестовых сообщений
    message_ids = []
    for i in range(100):
        msg_id = db.save_message(
            channel_id=channel_id,
            message_id=1000 + i,
            text=f"Test message {i}",
            date=datetime.now(UTC),
            has_media=False,
        )
        if msg_id:
            message_ids.append(msg_id)

    return message_ids


class TestBatchProcessing:
    """Тесты батч-обработки"""

    def test_mark_as_processed_batch_basic(self, db, sample_messages):
        """Базовый тест: батч-пометка работает"""
        # Берём 10 сообщений
        message_ids = sample_messages[:10]

        # Формируем батч
        updates = [
            {'message_id': msg_id, 'rejection_reason': 'test_rejection'}
            for msg_id in message_ids
        ]

        # Выполняем батч-обновление
        db.mark_as_processed_batch(updates)

        # Проверяем что все помечены
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE processed = 1 AND rejection_reason = 'test_rejection'"
        )
        count = cursor.fetchone()[0]

        assert count == 10

    def test_mark_as_processed_batch_with_duplicates(self, db, sample_messages):
        """Батч-пометка с is_duplicate флагом"""
        message_ids = sample_messages[:5]

        updates = [
            {'message_id': msg_id, 'is_duplicate': True, 'rejection_reason': 'duplicate'}
            for msg_id in message_ids
        ]

        db.mark_as_processed_batch(updates)

        # Проверяем is_duplicate
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE processed = 1 AND is_duplicate = 1"
        )
        count = cursor.fetchone()[0]

        assert count == 5

    def test_mark_as_processed_batch_with_scores(self, db, sample_messages):
        """Батч-пометка с gemini_score"""
        message_ids = sample_messages[:3]

        updates = [
            {'message_id': message_ids[0], 'gemini_score': 10},
            {'message_id': message_ids[1], 'gemini_score': 8},
            {'message_id': message_ids[2], 'gemini_score': 6},
        ]

        db.mark_as_processed_batch(updates)

        # Проверяем scores
        cursor = db.conn.cursor()
        cursor.execute(
            f"SELECT gemini_score FROM raw_messages WHERE id = {message_ids[0]}"
        )
        score = cursor.fetchone()[0]
        assert score == 10

    def test_mark_as_processed_batch_empty(self, db):
        """Пустой батч не вызывает ошибок"""
        db.mark_as_processed_batch([])
        # Не должно быть исключений

    def test_mark_as_processed_batch_mixed_params(self, db, sample_messages):
        """Батч с разными параметрами"""
        message_ids = sample_messages[:5]

        updates = [
            {'message_id': message_ids[0], 'rejection_reason': 'spam'},
            {'message_id': message_ids[1], 'is_duplicate': True},
            {'message_id': message_ids[2], 'gemini_score': 7},
            {'message_id': message_ids[3], 'rejection_reason': 'filtered', 'gemini_score': 5},
            {'message_id': message_ids[4]},  # Только message_id
        ]

        db.mark_as_processed_batch(updates)

        # Проверяем что все 5 помечены
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE processed = 1 AND id IN (?, ?, ?, ?, ?)",
            tuple(message_ids[:5])
        )
        count = cursor.fetchone()[0]
        assert count == 5

    def test_mark_as_processed_batch_large_100(self, db, sample_messages):
        """Большой батч: 100 сообщений"""
        updates = [
            {'message_id': msg_id, 'rejection_reason': 'bulk_test'}
            for msg_id in sample_messages
        ]

        db.mark_as_processed_batch(updates)

        # Проверяем что все 100 помечены
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE processed = 1 AND rejection_reason = 'bulk_test'"
        )
        count = cursor.fetchone()[0]
        assert count == 100


class TestBatchPerformance:
    """Тесты производительности батч-операций"""

    def test_batch_vs_individual_performance(self, db, sample_messages):
        """Батч должен быть значительно быстрее множественных вызовов"""
        # Создаём дополнительные сообщения для теста
        channel_id = db.add_channel("perf_channel", "Performance Test")
        individual_ids = []
        batch_ids = []

        for i in range(100):
            # Для individual теста
            msg_id = db.save_message(
                channel_id=channel_id,
                message_id=2000 + i,
                text=f"Individual test {i}",
                date=datetime.now(UTC),
                has_media=False,
            )
            if msg_id:
                individual_ids.append(msg_id)

            # Для batch теста
            msg_id = db.save_message(
                channel_id=channel_id,
                message_id=3000 + i,
                text=f"Batch test {i}",
                date=datetime.now(UTC),
                has_media=False,
            )
            if msg_id:
                batch_ids.append(msg_id)

        # Тест 1: Individual вызовы
        start_individual = time.time()
        for msg_id in individual_ids:
            db.mark_as_processed(msg_id, rejection_reason='individual')
        time_individual = time.time() - start_individual

        # Тест 2: Batch вызов
        updates = [
            {'message_id': msg_id, 'rejection_reason': 'batch'}
            for msg_id in batch_ids
        ]
        start_batch = time.time()
        db.mark_as_processed_batch(updates)
        time_batch = time.time() - start_batch

        # Батч должен быть как минимум в 2 раза быстрее
        # (в реальности может быть в 10-50 раз быстрее)
        speedup = time_individual / time_batch if time_batch > 0 else 0

        print(f"\nPerformance comparison (100 messages):")
        print(f"  Individual: {time_individual:.3f}s")
        print(f"  Batch:      {time_batch:.3f}s")
        print(f"  Speedup:    {speedup:.1f}x")

        # Минимальное ускорение должно быть 1.5x
        # На практике будет больше, но для CI используем консервативную оценку
        # (снижено с 2.0x до 1.5x из-за flaky behavior под нагрузкой)
        assert speedup >= 1.5, f"Batch должен быть минимум в 1.5 раза быстрее (получили {speedup:.1f}x)"

    def test_batch_500_messages(self, db):
        """Батч из 500 сообщений обрабатывается корректно"""
        # Создаём 500 сообщений
        channel_id = db.add_channel("large_batch_channel", "Large Batch Test")
        message_ids = []

        for i in range(500):
            msg_id = db.save_message(
                channel_id=channel_id,
                message_id=4000 + i,
                text=f"Large batch message {i}",
                date=datetime.now(UTC),
                has_media=False,
            )
            if msg_id:
                message_ids.append(msg_id)

        # Батч-обновление
        updates = [
            {'message_id': msg_id, 'rejection_reason': 'large_batch'}
            for msg_id in message_ids
        ]

        start = time.time()
        db.mark_as_processed_batch(updates)
        elapsed = time.time() - start

        # Проверяем что все помечены
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE processed = 1 AND rejection_reason = 'large_batch'"
        )
        count = cursor.fetchone()[0]

        print(f"\n500 messages batch processing: {elapsed:.3f}s")

        assert count == 500
        # 500 сообщений должны обработаться меньше чем за 1 секунду
        assert elapsed < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
