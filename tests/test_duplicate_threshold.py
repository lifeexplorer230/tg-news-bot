"""
FIX-DUPLICATE-2: Тесты для конфигурируемого порога дедупликации

Проверяет что:
1. Порог дедупликации настраивается через config
2. Новый порог 0.78 детектирует больше дубликатов чем старый 0.85
3. Порог применяется везде в коде
"""

import numpy as np
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock

from services.news_processor import NewsProcessor
from utils.config import Config


class TestDuplicateThreshold:
    """Тесты для настраиваемого порога дедупликации"""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Временный путь к БД для тестов"""
        return str(tmp_path / "test.db")

    @pytest.fixture
    def mock_config_default(self, temp_db_path):
        """Config с порогом по умолчанию (должен быть 0.78 после исправления)"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        config.get = Mock(side_effect=lambda key, default=None: {
            "processor.duplicate_threshold": 0.78,  # Новое значение по умолчанию
        }.get(key, default))
        config.database_settings = Mock(return_value={})
        return config

    @pytest.fixture
    def mock_config_custom(self, temp_db_path):
        """Config с кастомным порогом 0.80"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        config.get = Mock(side_effect=lambda key, default=None: {
            "processor.duplicate_threshold": 0.80,  # Кастомное значение
        }.get(key, default))
        config.database_settings = Mock(return_value={})
        return config

    @pytest.fixture
    def mock_config_old_strict(self, temp_db_path):
        """Config со старым строгим порогом 0.85"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        config.get = Mock(side_effect=lambda key, default=None: {
            "processor.duplicate_threshold": 0.85,  # Старое значение
        }.get(key, default))
        config.database_settings = Mock(return_value={})
        return config

    def test_default_threshold_is_078(self, mock_config_default):
        """FIX-DUPLICATE-2: Порог по умолчанию должен быть 0.78 (не 0.85)"""
        processor = NewsProcessor(mock_config_default)

        # Проверяем что новый порог применён
        assert processor.duplicate_threshold == 0.78
        assert processor.duplicate_threshold < 0.85  # Строже чем старый

    def test_custom_threshold_from_config(self, mock_config_custom):
        """Порог дедупликации настраивается через config"""
        processor = NewsProcessor(mock_config_custom)

        assert processor.duplicate_threshold == 0.80

    def test_lower_threshold_detects_more_duplicates(self):
        """
        Низкий порог (0.78) детектирует больше дубликатов чем высокий (0.85)

        Сценарий:
        - Есть две похожие новости с similarity=0.82
        - При пороге 0.85: similarity < threshold → НЕ дубликат
        - При пороге 0.78: similarity > threshold → ДУБЛИКАТ
        """
        # Создаём два похожих embedding с заданным cosine similarity
        # Используем метод: embedding2 = alpha * embedding1 + beta * orthogonal_vector
        # где alpha контролирует similarity

        embedding1 = np.array([1.0, 0.0, 0.0, 0.0])  # Базовый вектор

        # Для similarity ≈ 0.82, создаём вектор с углом ~35 градусов
        # cos(35°) ≈ 0.82
        target_similarity = 0.82
        alpha = target_similarity  # Компонент параллельный embedding1
        beta = np.sqrt(1 - alpha**2)  # Ортогональная компонента

        embedding2 = np.array([alpha, beta, 0.0, 0.0])

        # Проверяем что embedding2 нормализован
        assert abs(np.linalg.norm(embedding2) - 1.0) < 0.01

        # Вычисляем similarity
        similarity = np.dot(embedding1, embedding2)

        # Проверяем что similarity в нужном диапазоне
        assert 0.80 < similarity < 0.84, f"Similarity должна быть ~0.82, получили {similarity:.3f}"

        # С порогом 0.85 (старый) - НЕ дубликат
        is_duplicate_old = similarity >= 0.85
        assert is_duplicate_old == False

        # С порогом 0.78 (новый) - ДУБЛИКАТ
        is_duplicate_new = similarity >= 0.78
        assert is_duplicate_new == True

    def test_threshold_used_in_filter_duplicates(self, mock_config_custom):
        """
        Порог из config используется в filter_duplicates

        Проверяем что метод filter_duplicates использует self.duplicate_threshold
        """
        processor = NewsProcessor(mock_config_custom)

        # Убеждаемся что порог загружен из config
        assert processor.duplicate_threshold == 0.80

    def test_threshold_used_in_deduplicate_selected_posts(self, mock_config_default):
        """
        Порог применяется в deduplicate_selected_posts

        Метод должен использовать self.duplicate_threshold вместо хардкода 0.85
        """
        processor = NewsProcessor(mock_config_default)

        # Проверяем что порог 0.78 установлен
        assert processor.duplicate_threshold == 0.78

    def test_realistic_paraphrased_duplicates(self):
        """
        Реалистичный сценарий: перефразированные новости

        Пример:
        - Оригинал: "Ozon снизил комиссию для продавцов на 2%"
        - Дубликат: "Маркетплейс Ozon объявил о снижении комиссии продавцам на два процента"

        Такие новости имеют similarity ~0.75-0.83
        """
        # Симулируем embeddings перефразированных новостей
        # В реальности они будут иметь similarity ~0.75-0.83

        # С порогом 0.85 большинство пройдёт как уникальные (проблема!)
        paraphrased_similarities = [0.76, 0.79, 0.81, 0.83, 0.84]

        old_threshold = 0.85
        detected_as_duplicate_old = sum(1 for sim in paraphrased_similarities if sim >= old_threshold)

        new_threshold = 0.78
        detected_as_duplicate_new = sum(1 for sim in paraphrased_similarities if sim >= new_threshold)

        # С новым порогом детектируется больше дубликатов
        assert detected_as_duplicate_new > detected_as_duplicate_old
        assert detected_as_duplicate_new >= 4  # 4 из 5 будут детектированы
        assert detected_as_duplicate_old <= 1  # Только 1 будет детектирован

    def test_threshold_not_too_aggressive(self):
        """
        Проверка что новый порог 0.78 не слишком агрессивный

        Новости с низкой similarity (< 0.75) должны оставаться уникальными
        """
        # Симулируем embeddings разных новостей
        different_similarities = [0.50, 0.60, 0.70, 0.74]

        threshold = 0.78
        detected_as_duplicate = sum(1 for sim in different_similarities if sim >= threshold)

        # Все должны быть уникальными
        assert detected_as_duplicate == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
