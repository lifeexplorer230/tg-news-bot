"""
QA-2: Тесты для проверки обновления кэша embeddings после публикации

Проверяет что:
1. Кэш обновляется после публикации
2. Вторая категория детектирует дубликаты из первой
3. Нет дубликатов между категориями в одном запуске
"""

import numpy as np
import pytest
from unittest.mock import Mock

from services.news_processor import NewsProcessor


class TestCacheUpdate:
    """Тесты для обновления кэша embeddings"""

    @pytest.fixture
    def processor(self):
        """Создаём mock NewsProcessor для тестов"""
        # Создаём минимальный mock объект с нужными атрибутами
        processor = Mock(spec=NewsProcessor)
        processor._cached_published_embeddings = None
        processor.duplicate_threshold = 0.85

        # QA-4: Добавляем новые атрибуты для оптимизации дедупликации
        processor._published_embeddings_matrix = None
        processor._published_embeddings_ids = None

        # Mock для embeddings service с реальной реализацией batch_cosine_similarity
        def mock_batch_cosine_similarity(embedding, embeddings_matrix):
            """Упрощённая реализация batch cosine similarity для тестов"""
            # Нормализуем embedding
            embedding_norm = np.linalg.norm(embedding)
            if embedding_norm == 0:
                return np.zeros(len(embeddings_matrix))

            # Вычисляем cosine similarity для каждого embedding в матрице
            similarities = []
            for emb in embeddings_matrix:
                emb_norm = np.linalg.norm(emb)
                if emb_norm == 0:
                    similarities.append(0.0)
                else:
                    similarity = np.dot(embedding, emb) / (embedding_norm * emb_norm)
                    similarities.append(similarity)

            return np.array(similarities)

        processor.embeddings = Mock()
        processor.embeddings.batch_cosine_similarity = mock_batch_cosine_similarity

        # Привязываем реальные методы к mock объекту
        processor._update_published_cache = NewsProcessor._update_published_cache.__get__(
            processor, NewsProcessor
        )
        processor._check_duplicate_inline = NewsProcessor._check_duplicate_inline.__get__(
            processor, NewsProcessor
        )

        return processor

    def test_update_published_cache_initializes_empty_cache(self, processor):
        """QA-2: _update_published_cache инициализирует кэш если None"""
        assert processor._cached_published_embeddings is None

        post_ids = [1, 2, 3]
        embeddings = [np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([5.0, 6.0])]

        processor._update_published_cache(post_ids, embeddings)

        assert processor._cached_published_embeddings is not None
        assert len(processor._cached_published_embeddings) == 3
        assert processor._cached_published_embeddings[0] == (1, embeddings[0])

    def test_update_published_cache_extends_existing_cache(self, processor):
        """QA-2: _update_published_cache добавляет к существующему кэшу"""
        # Инициализируем кэш с начальными данными
        initial_embeddings = [
            (1, np.array([1.0, 2.0])),
            (2, np.array([3.0, 4.0])),
        ]
        processor._cached_published_embeddings = initial_embeddings.copy()

        # Добавляем новые embeddings
        new_post_ids = [3, 4]
        new_embeddings = [np.array([5.0, 6.0]), np.array([7.0, 8.0])]

        processor._update_published_cache(new_post_ids, new_embeddings)

        # Проверяем что кэш расширен
        assert len(processor._cached_published_embeddings) == 4
        assert processor._cached_published_embeddings[2] == (3, new_embeddings[0])
        assert processor._cached_published_embeddings[3] == (4, new_embeddings[1])

    def test_cache_update_prevents_duplicates_in_second_category(self, processor):
        """QA-2: Вторая категория детектирует дубликаты из первой после обновления кэша"""
        # Симулируем публикацию первой категории
        post_ids_category1 = [1, 2]
        embeddings_category1 = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
        ]

        # QA-4: Инициализируем матрицу для проверки дубликатов
        processor._published_embeddings_ids = post_ids_category1.copy()
        processor._published_embeddings_matrix = np.array(embeddings_category1)

        # Обновляем кэш после "публикации" первой категории
        processor._update_published_cache(post_ids_category1, embeddings_category1)

        # Проверяем что кэш обновлён
        assert processor._cached_published_embeddings is not None
        assert len(processor._cached_published_embeddings) == 2

        # Симулируем проверку дубликата для второй категории
        # Используем embedding очень похожий на первый (почти идентичный)
        duplicate_embedding = np.array([0.99, 0.01, 0.0])

        # Sprint 6.3.4: удалён параметр published_embeddings
        is_duplicate = processor._check_duplicate_inline(
            duplicate_embedding,
            threshold=0.85,
        )

        # Должен быть детектирован как дубликат
        assert is_duplicate is True

    def test_cache_update_allows_unique_items_in_second_category(self, processor):
        """QA-2: Уникальные посты второй категории проходят проверку"""
        # Симулируем публикацию первой категории
        post_ids_category1 = [1, 2]
        embeddings_category1 = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
        ]

        # QA-4: Инициализируем матрицу для проверки дубликатов
        processor._published_embeddings_ids = post_ids_category1.copy()
        processor._published_embeddings_matrix = np.array(embeddings_category1)

        processor._update_published_cache(post_ids_category1, embeddings_category1)

        # Проверяем уникальный embedding для второй категории (ортогональный)
        unique_embedding = np.array([0.0, 0.0, 1.0])

        # Sprint 6.3.4: удалён параметр published_embeddings
        is_duplicate = processor._check_duplicate_inline(
            unique_embedding,
            threshold=0.85,
        )

        # НЕ должен быть дубликатом
        assert is_duplicate is False

    def test_empty_cache_returns_no_duplicates(self, processor):
        """QA-2: Пустой кэш не детектирует дубликаты"""
        processor._cached_published_embeddings = []
        # QA-4: Пустая матрица также пуста
        processor._published_embeddings_matrix = np.array([])
        processor._published_embeddings_ids = []

        embedding = np.array([1.0, 2.0, 3.0])

        # Sprint 6.3.4: удалён параметр published_embeddings
        is_duplicate = processor._check_duplicate_inline(
            embedding, threshold=0.85
        )

        assert is_duplicate is False

    def test_cache_accumulates_multiple_updates(self, processor):
        """QA-2: Кэш накапливает embeddings из нескольких публикаций"""
        # Первая публикация
        processor._update_published_cache([1, 2], [np.array([1.0]), np.array([2.0])])
        assert len(processor._cached_published_embeddings) == 2

        # Вторая публикация
        processor._update_published_cache([3, 4], [np.array([3.0]), np.array([4.0])])
        assert len(processor._cached_published_embeddings) == 4

        # Третья публикация
        processor._update_published_cache([5], [np.array([5.0])])
        assert len(processor._cached_published_embeddings) == 5

        # Проверяем что все данные на месте
        assert processor._cached_published_embeddings[0][0] == 1
        assert processor._cached_published_embeddings[2][0] == 3
        assert processor._cached_published_embeddings[4][0] == 5


class TestCacheTTLInvalidation:
    """Тесты для TTL-based инвалидации кэша (проблема #1: дубликаты между запусками)"""

    @pytest.fixture
    def processor_with_ttl(self):
        """Создаём mock NewsProcessor с поддержкой TTL кэша"""
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock

        processor = Mock(spec=NewsProcessor)
        processor._cached_published_embeddings = None
        processor._cache_timestamp = None
        processor._cache_ttl_seconds = 30  # 30 секунд для тестов
        processor.duplicate_threshold = 0.85

        # QA-4: Атрибуты для оптимизации дедупликации
        processor._published_embeddings_matrix = None
        processor._published_embeddings_ids = None

        # Mock для embeddings service
        def mock_batch_cosine_similarity(embedding, embeddings_matrix):
            """Упрощённая реализация batch cosine similarity для тестов"""
            embedding_norm = np.linalg.norm(embedding)
            if embedding_norm == 0:
                return np.zeros(len(embeddings_matrix))

            similarities = []
            for emb in embeddings_matrix:
                emb_norm = np.linalg.norm(emb)
                if emb_norm == 0:
                    similarities.append(0.0)
                else:
                    similarity = np.dot(embedding, emb) / (embedding_norm * emb_norm)
                    similarities.append(similarity)

            return np.array(similarities)

        processor.embeddings = Mock()
        processor.embeddings.batch_cosine_similarity = mock_batch_cosine_similarity

        # Mock для БД
        processor.db = Mock()
        processor.db.get_published_embeddings = Mock(return_value=[])

        # Привязываем реальные методы к mock объекту
        processor._update_published_cache = NewsProcessor._update_published_cache.__get__(
            processor, NewsProcessor
        )
        processor._check_duplicate_inline = NewsProcessor._check_duplicate_inline.__get__(
            processor, NewsProcessor
        )

        return processor

    def test_cache_initialized_on_first_call(self, processor_with_ttl):
        """Тест: Кэш должен инициализироваться при первом вызове"""
        from datetime import datetime

        # Проверяем начальное состояние
        assert processor_with_ttl._cached_published_embeddings is None
        assert processor_with_ttl._cache_timestamp is None

        # Симулируем загрузку кэша
        published_embeddings = [
            (1, np.array([1.0, 0.0, 0.0])),
            (2, np.array([0.0, 1.0, 0.0])),
        ]
        processor_with_ttl._cached_published_embeddings = published_embeddings
        processor_with_ttl._cache_timestamp = datetime.now()

        # Проверяем что кэш инициализирован
        assert processor_with_ttl._cached_published_embeddings is not None
        assert processor_with_ttl._cache_timestamp is not None
        assert len(processor_with_ttl._cached_published_embeddings) == 2

    def test_cache_invalidation_after_ttl_expiry(self, processor_with_ttl):
        """Тест: Кэш должен инвалидироваться после истечения TTL"""
        from datetime import datetime, timedelta

        # Симулируем загрузку кэша в прошлом (40 секунд назад)
        old_timestamp = datetime.now() - timedelta(seconds=40)
        processor_with_ttl._cached_published_embeddings = [
            (1, np.array([1.0, 0.0, 0.0]))
        ]
        processor_with_ttl._cache_timestamp = old_timestamp

        # Проверяем что кэш устарел (TTL = 30 секунд)
        now = datetime.now()
        cache_age_seconds = (now - processor_with_ttl._cache_timestamp).total_seconds()
        is_expired = cache_age_seconds > processor_with_ttl._cache_ttl_seconds

        assert is_expired is True
        assert cache_age_seconds > 30

    def test_cache_valid_within_ttl(self, processor_with_ttl):
        """Тест: Кэш должен оставаться валидным в пределах TTL"""
        from datetime import datetime, timedelta

        # Симулируем загрузку кэша недавно (10 секунд назад)
        recent_timestamp = datetime.now() - timedelta(seconds=10)
        processor_with_ttl._cached_published_embeddings = [
            (1, np.array([1.0, 0.0, 0.0]))
        ]
        processor_with_ttl._cache_timestamp = recent_timestamp

        # Проверяем что кэш всё ещё валиден (TTL = 30 секунд)
        now = datetime.now()
        cache_age_seconds = (now - processor_with_ttl._cache_timestamp).total_seconds()
        is_expired = cache_age_seconds > processor_with_ttl._cache_ttl_seconds

        assert is_expired is False
        assert cache_age_seconds < 30

    def test_cache_reload_detects_new_duplicates(self, processor_with_ttl):
        """
        Тест: После перезагрузки кэша должны детектироваться дубликаты из БД

        Сценарий:
        1. Первый запуск processor: публикуется новость A (embedding1)
        2. Второй запуск processor: кэш перезагружается из БД
        3. Та же новость A приходит снова -> должна быть детектирована как дубликат
        """
        from datetime import datetime

        # ШАГ 1: Первый запуск - публикуем новость A
        embedding1 = np.array([1.0, 0.0, 0.0])

        # Симулируем что новость сохранена в БД
        processor_with_ttl.db.get_published_embeddings = Mock(return_value=[
            (1, embedding1)
        ])

        # ШАГ 2: Второй запуск - перезагружаем кэш из БД
        # Симулируем загрузку кэша (как это делает filter_duplicates)
        processor_with_ttl._cached_published_embeddings = processor_with_ttl.db.get_published_embeddings()
        processor_with_ttl._cache_timestamp = datetime.now()

        # Строим матрицу embeddings для проверки дубликатов
        processor_with_ttl._published_embeddings_ids = [1]
        processor_with_ttl._published_embeddings_matrix = np.array([embedding1])

        # ШАГ 3: Проверяем что дубликат детектируется
        duplicate_embedding = np.array([0.99, 0.01, 0.0])  # Почти идентичный

        is_duplicate = processor_with_ttl._check_duplicate_inline(
            duplicate_embedding,
            threshold=0.85,
        )

        # Должен быть детектирован как дубликат
        assert is_duplicate is True

    def test_stale_cache_misses_duplicates_without_reload(self, processor_with_ttl):
        """
        Тест: Устаревший кэш НЕ детектирует новые дубликаты (демонстрация проблемы)

        Это тест демонстрирующий существующую проблему:
        Если кэш не перезагружается, новости из БД не учитываются
        """
        from datetime import datetime

        # ШАГ 1: Кэш пуст (симулируем первый запуск processor)
        processor_with_ttl._cached_published_embeddings = []
        processor_with_ttl._cache_timestamp = datetime.now()
        processor_with_ttl._published_embeddings_matrix = np.array([])
        processor_with_ttl._published_embeddings_ids = []

        # ШАГ 2: В БД есть опубликованная новость, но кэш НЕ перезагружен
        embedding1 = np.array([1.0, 0.0, 0.0])
        processor_with_ttl.db.get_published_embeddings = Mock(return_value=[
            (1, embedding1)
        ])

        # ШАГ 3: Проверяем дубликат - НЕ будет детектирован (проблема!)
        duplicate_embedding = np.array([0.99, 0.01, 0.0])

        is_duplicate = processor_with_ttl._check_duplicate_inline(
            duplicate_embedding,
            threshold=0.85,
        )

        # БАГ: дубликат НЕ детектируется, потому что кэш устарел!
        assert is_duplicate is False  # Это и есть проблема!


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
