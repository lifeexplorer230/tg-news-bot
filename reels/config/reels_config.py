"""
Конфигурация для Reels Generator модуля

Обертка над основной конфигурацией ТНБ для удобного доступа
к настройкам Reels модуля.
"""

from typing import Optional, List
from pathlib import Path

from utils.config import Config


class ReelsConfig:
    """Обертка для конфигурации Reels модуля"""

    def __init__(self, config: Config):
        """
        Инициализация конфигурации

        Args:
            config: Основная конфигурация из ТНБ
        """
        self.config = config

    # Perplexity API настройки

    @property
    def perplexity_api_key(self) -> str:
        """Perplexity API ключ"""
        return self.config.get("perplexity.api_key", "")

    @property
    def perplexity_model(self) -> str:
        """Модель Perplexity (sonar-pro, sonar, etc.)"""
        return self.config.get("perplexity.model", "sonar-pro")

    @property
    def perplexity_base_url(self) -> str:
        """Base URL для Perplexity API"""
        return self.config.get("perplexity.base_url", "https://api.perplexity.ai")

    @property
    def perplexity_timeout(self) -> int:
        """Timeout для запросов к Perplexity (секунды)"""
        return self.config.get("perplexity.timeout", 60)

    @property
    def perplexity_max_retries(self) -> int:
        """Максимальное количество попыток при ошибках"""
        return self.config.get("perplexity.max_retries", 3)

    # Настройки процессора

    @property
    def news_limit(self) -> int:
        """Количество новостей для обработки"""
        return self.config.get("reels_processor.news_limit", 10)

    @property
    def filter_by_category(self) -> Optional[List[str]]:
        """Фильтр по категориям новостей"""
        categories = self.config.get("reels_processor.filter_by_category", [])
        return categories if categories else None

    @property
    def auto_run_after_processor(self) -> bool:
        """Автоматический запуск после processor"""
        return self.config.get("reels_processor.auto_run_after_processor", False)

    # Пути к промптам

    def get_prompt_path(self, prompt_name: str) -> Path:
        """
        Получить путь к файлу промпта

        Args:
            prompt_name: Имя промпта (enrich_news, generate_reels)

        Returns:
            Path к файлу промпта
        """
        path_str = self.config.get(f"reels_processor.prompts.{prompt_name}")
        if not path_str:
            raise ValueError(f"Промпт '{prompt_name}' не найден в конфигурации")
        return Path(path_str)

    def load_prompt(self, prompt_name: str) -> str:
        """
        Загрузить содержимое промпта

        Args:
            prompt_name: Имя промпта

        Returns:
            Содержимое промпта
        """
        prompt_path = self.get_prompt_path(prompt_name)
        if not prompt_path.exists():
            raise FileNotFoundError(f"Файл промпта не найден: {prompt_path}")
        return prompt_path.read_text(encoding='utf-8')

    # БД настройки

    @property
    def db_source_profile(self) -> str:
        """Профиль для источника новостей из БД"""
        return self.config.get("reels_processor.db_source.profile", "ai")

    @property
    def db_source_table(self) -> str:
        """Таблица для источника новостей"""
        return self.config.get("reels_processor.db_source.table", "published")

    @property
    def db_source_days_back(self) -> int:
        """Количество дней назад для выборки новостей"""
        return self.config.get("reels_processor.db_source.days_back", 1)

    # Вывод результатов

    @property
    def telegram_output_enabled(self) -> bool:
        """Включена ли отправка в Telegram"""
        return self.config.get("output.telegram.enabled", True)

    @property
    def telegram_output_channel(self) -> str:
        """Канал для отправки сценариев"""
        return self.config.get("output.telegram.channel", "")

    @property
    def telegram_output_format(self) -> str:
        """Формат вывода (detailed, compact)"""
        return self.config.get("output.telegram.format", "detailed")

    @property
    def file_output_enabled(self) -> bool:
        """Включено ли сохранение в файлы"""
        return self.config.get("output.file.enabled", False)

    @property
    def file_output_path(self) -> Path:
        """Путь для сохранения результатов"""
        path_str = self.config.get("output.file.path", "./data/reels_output")
        return Path(path_str)

    # Логирование

    @property
    def log_tokens(self) -> bool:
        """Логировать ли использование токенов"""
        return self.config.get("logging.log_tokens", True)

    # Telegram настройки (из основной конфигурации)

    @property
    def telegram_api_id(self) -> int:
        """Telegram API ID (из переменных окружения)"""
        import os
        return int(os.getenv("TELEGRAM_API_ID", "0"))

    @property
    def telegram_api_hash(self) -> str:
        """Telegram API Hash (из переменных окружения)"""
        import os
        return os.getenv("TELEGRAM_API_HASH", "")

    @property
    def telegram_session_file(self) -> str:
        """Путь к session файлу Telegram"""
        return self.config.get("telegram.session_name", "./sessions/ai/session")

    def validate(self) -> bool:
        """
        Валидация конфигурации

        Returns:
            True если конфигурация валидна

        Raises:
            ValueError: Если конфигурация невалидна
        """
        # Проверить обязательные параметры
        if not self.perplexity_api_key:
            raise ValueError("PERPLEXITY_API_KEY не установлен в .env")

        # Проверить что промпты существуют
        try:
            self.load_prompt("enrich_news")
            self.load_prompt("generate_reels")
        except (ValueError, FileNotFoundError) as e:
            raise ValueError(f"Ошибка загрузки промптов: {e}")

        # Проверить Telegram настройки если вывод включен
        if self.telegram_output_enabled:
            if not self.telegram_output_channel:
                raise ValueError("output.telegram.channel не установлен в конфигурации")
            if not self.telegram_api_id or not self.telegram_api_hash:
                raise ValueError("Telegram API credentials не установлены")

        return True
