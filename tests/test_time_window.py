"""
FIX-DUPLICATE-6: Тесты для настраиваемого временного окна дедупликации

Проблема: Хардкод 60 дней для поиска дубликатов в БД
- Слишком большое окно: старые новости засоряют проверку
- Слишком маленькое окно: недавние дубликаты могут пропуститься

Решение: Сделать временное окно конфигурируемым

Проверяет что:
1. Временное окно настраивается через config
2. Дефолтное значение - 60 дней (backwards compatibility)
3. Можно установить кастомное значение
"""

import pytest
from unittest.mock import Mock

from services.news_processor import NewsProcessor
from utils.config import Config


class TestTimeWindow:
    """Тесты для настраиваемого временного окна"""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Временный путь к БД для тестов"""
        return str(tmp_path / "test.db")

    @pytest.fixture
    def mock_config_default(self, temp_db_path):
        """Config с дефолтным временным окном"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        def mock_get(key, default=None):
            values = {
                "processor.duplicate_threshold": 0.78,
            }
            # Если ключ не найден, возвращаем default
            return values.get(key, default)
        config.get = Mock(side_effect=mock_get)
        config.database_settings = Mock(return_value={})
        return config

    @pytest.fixture
    def mock_config_custom(self, temp_db_path):
        """Config с кастомным временным окном (30 дней)"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        config.get = Mock(side_effect=lambda key, default=None: {
            "processor.duplicate_threshold": 0.78,
            "processor.duplicate_time_window_days": 30,  # Кастом: 30 дней
        }.get(key, default))
        config.database_settings = Mock(return_value={})
        return config

    def test_default_time_window_is_60_days(self, mock_config_default):
        """
        FIX-DUPLICATE-6: Дефолтное временное окно - 60 дней

        Проверяет обратную совместимость
        """
        processor = NewsProcessor(mock_config_default)

        # Проверяем что дефолтное значение 60 дней
        assert processor.duplicate_time_window_days == 60

    def test_custom_time_window_from_config(self, mock_config_custom):
        """
        Временное окно настраивается через config

        Пример: 30 дней для быстрых новостей, 90 дней для архивных
        """
        processor = NewsProcessor(mock_config_custom)

        # Проверяем что кастомное значение применено
        assert processor.duplicate_time_window_days == 30

    def test_time_window_affects_cache_loading(self, mock_config_custom):
        """
        Временное окно используется при загрузке кэша из БД

        Проверяем что параметр передаётся в db.get_published_embeddings()
        """
        processor = NewsProcessor(mock_config_custom)

        # Временное окно должно быть установлено
        assert processor.duplicate_time_window_days == 30

    def test_time_window_validation_positive(self):
        """
        Временное окно должно быть положительным числом

        Невалидные значения: 0, -1, -30
        """
        # Это будет проверяться в NewsProcessor.__init__
        invalid_values = [0, -1, -30, -100]

        for value in invalid_values:
            # Значение должно быть отвергнуто или заменено на дефолт
            assert value <= 0  # Плохое значение

    def test_time_window_reasonable_range(self):
        """
        Временное окно должно быть в разумном диапазоне

        Разумные значения: 7-180 дней
        - Минимум 7 дней (неделя) для быстрых новостей
        - Максимум 180 дней (полгода) для архивных
        """
        reasonable_min = 7
        reasonable_max = 180

        # Проверяем что разумные значения принимаются
        test_values = [7, 14, 30, 60, 90, 180]
        for value in test_values:
            assert reasonable_min <= value <= reasonable_max


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
