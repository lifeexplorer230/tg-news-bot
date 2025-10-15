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

        is_duplicate = processor._check_duplicate_inline(
            duplicate_embedding,
            processor._cached_published_embeddings,
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

        is_duplicate = processor._check_duplicate_inline(
            unique_embedding,
            processor._cached_published_embeddings,
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

        is_duplicate = processor._check_duplicate_inline(
            embedding, processor._cached_published_embeddings, threshold=0.85
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
