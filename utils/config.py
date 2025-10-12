"""Загрузка конфигурации из YAML и .env"""
import os
from typing import Any

import yaml
from dotenv import load_dotenv


class Config:
    """Класс для работы с конфигурацией"""

    def __init__(self, config_path: str = "config.yaml", env_path: str = ".env"):
        """
        Инициализация конфигурации

        Args:
            config_path: Путь к config.yaml
            env_path: Путь к .env файлу
        """
        # Загружаем .env
        load_dotenv(env_path)

        # Загружаем config.yaml
        with open(config_path, encoding="utf-8") as f:
            self.config: dict[str, Any] = yaml.safe_load(f)

        # API ключи из .env
        self.telegram_api_id = int(os.getenv("TELEGRAM_API_ID"))
        self.telegram_api_hash = os.getenv("TELEGRAM_API_HASH")
        self.telegram_phone = os.getenv("TELEGRAM_PHONE", "")
        self.my_channel = os.getenv("MY_CHANNEL", "")
        self.my_personal_account = os.getenv("MY_PERSONAL_ACCOUNT", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Получить значение из конфига по пути (через точку)

        Args:
            key_path: Путь к ключу, например "telegram.session_name"
            default: Значение по умолчанию

        Returns:
            Значение из конфига или default
        """
        keys = key_path.split(".")
        value = self.config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    @property
    def db_path(self) -> str:
        """Путь к базе данных"""
        return self.get("database.path", "./data/news.db")

    @property
    def log_file(self) -> str:
        """Путь к файлу логов"""
        return self.get("logging.file", "./logs/bot.log")

    @property
    def log_level(self) -> str:
        """Уровень логирования"""
        return self.get("logging.level", "INFO")

    @property
    def log_format(self) -> str:
        """Формат сообщений логирования"""
        return self.get("logging.format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    @property
    def log_date_format(self) -> str:
        """Формат даты в логах"""
        return self.get("logging.datefmt", "%Y-%m-%d %H:%M:%S")

    @property
    def log_rotation(self) -> dict[str, Any]:
        """Настройки rotate для логов"""
        value = self.get("logging.rotate", {})
        return value or {}


# Глобальный экземпляр конфига
config = None


def load_config(config_path: str = "config.yaml", env_path: str = ".env") -> Config:
    """Загрузить конфигурацию"""
    global config
    config = Config(config_path, env_path)
    return config


def get_config() -> Config:
    """Получить глобальный экземпляр конфига"""
    global config
    if config is None:
        config = load_config()
    return config
