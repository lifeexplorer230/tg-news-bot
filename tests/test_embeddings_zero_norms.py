"""
QA-5: Тесты для обработки нулевых норм в cosine_similarity

Проверяет что:
1. Нулевые нормы возвращают 0.0
2. Нет NaN в результатах
3. Backwards compatible с существующими тестами
"""

import numpy as np
import pytest

from services.embeddings import EmbeddingService


class TestCosineZeroNorms:
    """Тесты для обработки нулевых норм"""

    def test_cosine_similarity_both_zero_norms(self):
        """QA-5: Оба embedding с нулевой нормой возвращают 0.0"""
        embedding1 = np.array([0.0, 0.0, 0.0])
        embedding2 = np.array([0.0, 0.0, 0.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert result == 0.0
        assert not np.isnan(result)

    def test_cosine_similarity_first_zero_norm(self):
        """QA-5: Первый embedding с нулевой нормой возвращает 0.0"""
        embedding1 = np.array([0.0, 0.0, 0.0])
        embedding2 = np.array([1.0, 2.0, 3.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert result == 0.0
        assert not np.isnan(result)

    def test_cosine_similarity_second_zero_norm(self):
        """QA-5: Второй embedding с нулевой нормой возвращает 0.0"""
        embedding1 = np.array([1.0, 2.0, 3.0])
        embedding2 = np.array([0.0, 0.0, 0.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert result == 0.0
        assert not np.isnan(result)

    def test_cosine_similarity_normal_vectors(self):
        """QA-5: Нормальные векторы работают как ожидалось"""
        # Идентичные векторы → similarity = 1.0
        embedding1 = np.array([1.0, 0.0, 0.0])
        embedding2 = np.array([1.0, 0.0, 0.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert pytest.approx(result, abs=1e-6) == 1.0
        assert not np.isnan(result)

    def test_cosine_similarity_orthogonal_vectors(self):
        """QA-5: Ортогональные векторы → similarity = 0.0"""
        embedding1 = np.array([1.0, 0.0, 0.0])
        embedding2 = np.array([0.0, 1.0, 0.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert pytest.approx(result, abs=1e-6) == 0.0
        assert not np.isnan(result)

    def test_cosine_similarity_opposite_vectors(self):
        """QA-5: Противоположные векторы → similarity = -1.0"""
        embedding1 = np.array([1.0, 0.0, 0.0])
        embedding2 = np.array([-1.0, 0.0, 0.0])

        result = EmbeddingService.cosine_similarity(embedding1, embedding2)

        assert pytest.approx(result, abs=1e-6) == -1.0
        assert not np.isnan(result)

    def test_batch_cosine_similarity_handles_zero_norms(self):
        """QA-5: batch_cosine_similarity тоже обрабатывает нулевые нормы (уже было защищено)"""
        embedding = np.array([1.0, 2.0, 3.0])
        embeddings_matrix = np.array([
            [0.0, 0.0, 0.0],  # нулевая норма
            [1.0, 0.0, 0.0],  # нормальный
            [0.0, 1.0, 0.0],  # нормальный
        ])

        result = EmbeddingService.batch_cosine_similarity(embedding, embeddings_matrix)

        # Первый элемент должен быть 0.0 (нулевая норма)
        assert result[0] == 0.0
        assert not np.isnan(result[0])

        # Остальные элементы не NaN
        assert not np.any(np.isnan(result))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
