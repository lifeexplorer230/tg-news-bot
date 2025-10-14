"""Загрузка конфигурации с поддержкой профилей."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from models.config_schemas import AppConfig, EnvConfig

DEFAULT_BASE_PATH = Path("config/base.yaml")
DEFAULT_PROFILES_DIR = Path("config/profiles")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {path}")
    with path.open(encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Файл конфигурации {path} должен содержать объект YAML")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивное объединение словарей, где override перекрывает base."""
    result: dict[str, Any] = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _format_string(template: str, context: dict[str, Any]) -> str:
    try:
        return template.format(**context)
    except KeyError:
        # Недостающие переменные игнорируем, возвращаем исходную строку
        return template


class Config:
    """Класс для работы с конфигурацией профилей."""

    def __init__(
        self,
        profile: str | None = None,
        *,
        base_path: str | Path = DEFAULT_BASE_PATH,
        profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
        env_path: str | Path = ".env",
        config_path: str | Path | None = None,
    ) -> None:
        load_dotenv(env_path)

        self._env_path = Path(env_path)
        self._base_path = Path(base_path)
        self._profiles_dir = Path(profiles_dir)
        self._config_path = Path(config_path) if config_path else None

        if self._config_path is not None:
            config_data = _read_yaml(self._config_path)
            self.profile = profile or os.getenv("PROFILE") or config_data.get("profile", "default")
            self.config: dict[str, Any] = config_data
        else:
            base_data = _read_yaml(self._base_path)
            profile_name = profile or os.getenv("PROFILE") or base_data.get("profile")
            if not profile_name:
                raise ValueError("Не задан профиль конфигурации (profile) и отсутствует переменная PROFILE")
            profile_path = self._profiles_dir / f"{profile_name}.yaml"
            profile_data = _read_yaml(profile_path)
            merged = _deep_merge(base_data, profile_data)
            merged["profile"] = profile_name
            self.profile = profile_name
            self.config = merged

        self._config_root = (
            self._config_path.parent if self._config_path else self._base_path.parent
        ).resolve()
        self._prompt_cache: dict[str, str] = {}

        # CR-H4: Валидация конфига с Pydantic перед использованием
        self._validate_config()

        self._apply_paths()
        self._load_env_keys()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        """
        Валидация конфига с Pydantic (CR-H4)

        Raises:
            ValueError: Если конфиг невалиден с понятным сообщением об ошибке
        """
        try:
            # Валидируем конфиг через Pydantic
            AppConfig(**self.config)
        except ValidationError as e:
            # Формируем дружелюбное сообщение об ошибке
            error_lines = ["\n❌ Ошибка валидации конфигурации:"]
            for error in e.errors():
                loc_path = " -> ".join(str(x) for x in error["loc"])
                msg = error["msg"]
                error_lines.append(f"  • {loc_path}: {msg}")
            error_lines.append("\nПроверьте config/base.yaml и профильный конфиг.")
            raise ValueError("\n".join(error_lines)) from e

    def _validate_env(self) -> None:
        """
        Валидация env переменных с Pydantic (CR-H4)

        Raises:
            ValueError: Если env переменные невалидны с понятным сообщением
        """
        try:
            # Собираем все env переменные
            env_vars = {
                "TELEGRAM_API_ID": os.getenv("TELEGRAM_API_ID", "0"),
                "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", ""),
                "TELEGRAM_PHONE": os.getenv("TELEGRAM_PHONE", ""),
                "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
                "MY_CHANNEL": os.getenv("MY_CHANNEL", ""),
                "MY_PERSONAL_ACCOUNT": os.getenv("MY_PERSONAL_ACCOUNT", ""),
            }
            # Валидируем через Pydantic
            EnvConfig(**env_vars)
        except ValidationError as e:
            # Формируем дружелюбное сообщение об ошибке
            error_lines = ["\n❌ Ошибка валидации env переменных (.env файл):"]
            for error in e.errors():
                field_name = error["loc"][0] if error["loc"] else "unknown"
                msg = error["msg"]
                error_lines.append(f"  • {field_name}: {msg}")
            error_lines.append("\nПроверьте файл .env и убедитесь что все переменные заполнены корректно.")
            raise ValueError("\n".join(error_lines)) from e

    def _apply_paths(self) -> None:
        paths = self.config.setdefault("paths", {})

        data_dir = paths.get("data_dir", "./data")
        logs_dir = paths.get("logs_dir", "./logs")
        sessions_dir = paths.get("sessions_dir", "./sessions")

        context = {
            "profile": self.profile,
            "data_dir": data_dir,
            "logs_dir": logs_dir,
            "sessions_dir": sessions_dir,
        }

        # Обновляем базовые директории с учётом возможных шаблонов
        data_dir = _format_string(data_dir, context)
        logs_dir = _format_string(logs_dir, context)
        sessions_dir = _format_string(sessions_dir, context)

        context.update({
            "data_dir": data_dir,
            "logs_dir": logs_dir,
            "sessions_dir": sessions_dir,
        })

        paths["data_dir"] = data_dir
        paths["logs_dir"] = logs_dir
        paths["sessions_dir"] = sessions_dir

        # Создаём директории, если они отсутствуют
        for directory in (data_dir, logs_dir, sessions_dir):
            Path(directory).mkdir(parents=True, exist_ok=True)

        # Готовим контекст для шаблонов
        db_pattern = paths.get("db_file_pattern")
        log_pattern = paths.get("log_file_pattern")
        session_pattern = paths.get("session_file_pattern")

        if session_pattern:
            session_pattern = _format_string(session_pattern, context)

        telegram_cfg = self.config.setdefault("telegram", {})
        session_name = telegram_cfg.get("session_name")
        if not session_name and session_pattern:
            session_name = session_pattern
        if session_name:
            telegram_cfg["session_name"] = _format_string(session_name, context)

        logging_cfg = self.config.setdefault("logging", {})
        log_file = logging_cfg.get("file")
        if log_file:
            logging_cfg["file"] = _format_string(log_file, context)
        elif log_pattern:
            logging_cfg["file"] = _format_string(log_pattern, context)
        else:
            logging_cfg["file"] = str(Path(logs_dir) / "bot.log")

        database_cfg = self.config.setdefault("database", {})
        db_path = database_cfg.get("path")
        if db_path:
            database_cfg["path"] = _format_string(db_path, context)
        elif db_pattern:
            database_cfg["path"] = _format_string(db_pattern, context)
        else:
            database_cfg["path"] = str(Path(data_dir) / f"{self.profile}.db")

        # Форматируем известные строки в listener.healthcheck
        listener_cfg = self.config.setdefault("listener", {})
        healthcheck_cfg = listener_cfg.get("healthcheck", {})
        if isinstance(healthcheck_cfg, dict):
            for key, value in healthcheck_cfg.items():
                if isinstance(value, str):
                    healthcheck_cfg[key] = _format_string(value, context)
            listener_cfg["healthcheck"] = healthcheck_cfg

        self.paths = context

    def _load_env_keys(self) -> None:
        # CR-H4: Валидация env переменных перед загрузкой
        self._validate_env()

        # Загружаем провалидированные значения
        self.telegram_api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.telegram_api_hash = os.getenv("TELEGRAM_API_HASH", "")
        self.telegram_phone = os.getenv("TELEGRAM_PHONE", "")
        self.my_channel = os.getenv("MY_CHANNEL", "")
        self.my_personal_account = os.getenv("MY_PERSONAL_ACCOUNT", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")

    # ------------------------------------------------------------------
    # Публичные методы и свойства
    # ------------------------------------------------------------------

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        value: Any = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    @property
    def db_path(self) -> str:
        return self.config.get("database", {}).get("path", "./data/news.db")

    @property
    def log_file(self) -> str:
        return self.config.get("logging", {}).get("file", "./logs/bot.log")

    @property
    def log_level(self) -> str:
        return self.config.get("logging", {}).get("level", "INFO")

    @property
    def log_format(self) -> str:
        return self.config.get("logging", {}).get(
            "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    @property
    def log_date_format(self) -> str:
        return self.config.get("logging", {}).get("datefmt", "%Y-%m-%d %H:%M:%S")

    @property
    def log_rotation(self) -> dict[str, Any]:
        return self.config.get("logging", {}).get("rotate", {})

    def database_settings(self) -> dict[str, Any]:
        settings = self.config.get("database", {}) or {}
        retry = settings.get("retry", {}) or {}
        return {
            "timeout": settings.get("timeout_seconds", 30.0),
            "busy_timeout_ms": settings.get("busy_timeout_ms", 30000),
            "retry_max_attempts": retry.get("max_attempts", 5),
            "retry_base_delay": retry.get("base_delay_seconds", 0.5),
            "retry_backoff_multiplier": retry.get("backoff_multiplier", 1.0),
        }

    def load_prompt(self, prompt_key: str) -> str | None:
        if prompt_key in self._prompt_cache:
            return self._prompt_cache[prompt_key]

        prompt_path = self.get(f"gemini.prompts.{prompt_key}")
        if not prompt_path:
            return None

        path = Path(prompt_path)
        if not path.is_absolute():
            path = (self._config_root / path).resolve()

        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

        self._prompt_cache[prompt_key] = text
        return text


_config_singleton: Config | None = None


def load_config(
    profile: str | None = None,
    *,
    env_path: str | Path = ".env",
    base_path: str | Path = DEFAULT_BASE_PATH,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
    config_path: str | Path | None = None,
) -> Config:
    """Загрузить конфигурацию. Хранит singleton для повторного использования."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = Config(
            profile,
            base_path=base_path,
            profiles_dir=profiles_dir,
            env_path=env_path,
            config_path=config_path,
        )
    return _config_singleton


def get_config() -> Config:
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


__all__ = ["Config", "load_config", "get_config"]
