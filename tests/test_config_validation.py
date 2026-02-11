"""
Тесты для валидации конфигурации (CR-H4)

Проверяем что Config корректно валидирует невалидные конфиги и env переменные,
выдавая дружелюбные error messages.
"""

from pathlib import Path

import pytest
import yaml

from utils.config import Config


@pytest.fixture
def valid_env(monkeypatch):
    """Валидные env переменные для тестов"""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "+12345678901")
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)
    monkeypatch.setenv("MY_CHANNEL", "@test")
    monkeypatch.setenv("MY_PERSONAL_ACCOUNT", "@owner")


@pytest.fixture
def minimal_valid_config(tmp_path):
    """Минимальный валидный конфиг для тестов"""
    config_dir = tmp_path / "config"
    profiles_dir = config_dir / "profiles"
    config_dir.mkdir()
    profiles_dir.mkdir()

    base_data = {
        "profile": "test",
        "paths": {
            "data_dir": str(tmp_path / "data"),
            "logs_dir": str(tmp_path / "logs"),
            "sessions_dir": str(tmp_path / "sessions"),
        },
        "database": {},
        "telegram": {},
        "listener": {
            "healthcheck": {}
        },
        "logging": {},
    }
    (config_dir / "base.yaml").write_text(
        yaml.safe_dump(base_data, sort_keys=False),
        encoding="utf-8",
    )

    # Создаём профильный файл test.yaml
    test_profile_data = {
        "profile": "test",
    }
    (profiles_dir / "test.yaml").write_text(
        yaml.safe_dump(test_profile_data, sort_keys=False),
        encoding="utf-8",
    )

    return config_dir


def test_invalid_database_timeout_negative(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """Тест CR-H4: Негативный timeout в database должен вызвать ошибку"""
    config_dir = minimal_valid_config

    # Модифицируем конфиг с невалидным timeout
    base_data = yaml.safe_load((config_dir / "base.yaml").read_text())
    base_data["database"]["timeout_seconds"] = -5.0
    (config_dir / "base.yaml").write_text(yaml.safe_dump(base_data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации конфигурации" in error_msg
    assert "database" in error_msg
    assert "timeout_seconds" in error_msg


def test_invalid_processor_schedule_time_format(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """Тест CR-H4: Невалидный формат schedule_time должен вызвать ошибку"""
    config_dir = minimal_valid_config

    # Модифицируем конфиг с невалидным schedule_time
    base_data = yaml.safe_load((config_dir / "base.yaml").read_text())
    base_data["processor"] = {"schedule_time": "25:99"}  # Невалидные часы и минуты
    (config_dir / "base.yaml").write_text(yaml.safe_dump(base_data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации конфигурации" in error_msg
    assert "schedule_time" in error_msg or "processor" in error_msg


def test_invalid_listener_mode(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """Тест CR-H4: Невалидный listener mode должен вызвать ошибку"""
    config_dir = minimal_valid_config

    # Модифицируем конфиг с невалидным mode
    base_data = yaml.safe_load((config_dir / "base.yaml").read_text())
    base_data["listener"]["mode"] = "invalid_mode"
    (config_dir / "base.yaml").write_text(yaml.safe_dump(base_data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации конфигурации" in error_msg
    assert "listener" in error_msg
    assert "mode" in error_msg


def test_invalid_log_level(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """Тест CR-H4: Невалидный log level должен вызвать ошибку"""
    config_dir = minimal_valid_config

    # Модифицируем конфиг с невалидным log level
    base_data = yaml.safe_load((config_dir / "base.yaml").read_text())
    base_data["logging"]["level"] = "INVALID_LEVEL"
    (config_dir / "base.yaml").write_text(yaml.safe_dump(base_data), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации конфигурации" in error_msg
    assert "logging" in error_msg
    assert "level" in error_msg


# ======================================================================
# Тесты env валидации
# ======================================================================

def test_invalid_telegram_api_id_not_number(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: Невалидный TELEGRAM_API_ID (не число) должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "not_a_number")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "+12345678901")
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "TELEGRAM_API_ID" in error_msg


def test_invalid_telegram_api_id_zero(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: TELEGRAM_API_ID = 0 должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "0")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "+12345678901")
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "TELEGRAM_API_ID" in error_msg
    # Проверяем что есть сообщение об ошибке (может быть разный текст от Pydantic)


def test_invalid_telegram_api_hash_too_short(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: Короткий TELEGRAM_API_HASH должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "short")  # Меньше 32 символов
    monkeypatch.setenv("TELEGRAM_PHONE", "+12345678901")
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "TELEGRAM_API_HASH" in error_msg


def test_invalid_telegram_phone_wrong_format(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: Невалидный формат TELEGRAM_PHONE должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "invalid_phone")  # Не соответствует паттерну
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "TELEGRAM_PHONE" in error_msg


def test_invalid_telegram_phone_no_plus(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: TELEGRAM_PHONE без '+' должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "12345678901")  # Без '+'
    monkeypatch.setenv("GEMINI_API_KEY", "test_" + "a" * 16)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "TELEGRAM_PHONE" in error_msg


def test_invalid_gemini_key_too_short(tmp_path, monkeypatch, minimal_valid_config):
    """Тест CR-H4: Короткий GEMINI_API_KEY должен вызвать ошибку"""
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "a" * 32)
    monkeypatch.setenv("TELEGRAM_PHONE", "+12345678901")
    monkeypatch.setenv("GEMINI_API_KEY", "short")  # Меньше 20 символов

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
    assert "GEMINI_API_KEY" in error_msg


def test_valid_config_passes_validation(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """Тест CR-H4: Валидный конфиг должен проходить валидацию без ошибок"""
    config_dir = minimal_valid_config

    # Должно пройти без ошибок
    cfg = Config(
        base_path=config_dir / "base.yaml",
        profiles_dir=config_dir / "profiles",
        env_path=tmp_path / ".env",
    )

    assert cfg.profile == "test"
    assert cfg.telegram_api_id == 12345
    assert len(cfg.telegram_api_hash) == 32
    assert cfg.telegram_phone.startswith("+")


def test_status_bot_token_optional(tmp_path, monkeypatch, minimal_valid_config, valid_env):
    """STATUS_BOT_TOKEN опционален — Config работает без него"""
    monkeypatch.delenv("STATUS_BOT_TOKEN", raising=False)
    config_dir = minimal_valid_config

    cfg = Config(
        base_path=config_dir / "base.yaml",
        profiles_dir=config_dir / "profiles",
        env_path=tmp_path / ".env",
    )
    assert cfg.profile == "test"


def test_empty_required_env_gives_clear_error(tmp_path, monkeypatch, minimal_valid_config):
    """Config с пустыми обязательными env → понятная ошибка ValueError"""
    # Не устанавливаем обязательные переменные
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("TELEGRAM_PHONE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    config_dir = minimal_valid_config

    with pytest.raises(ValueError) as exc_info:
        Config(
            base_path=config_dir / "base.yaml",
            profiles_dir=config_dir / "profiles",
            env_path=tmp_path / ".env",
        )

    error_msg = str(exc_info.value)
    assert "❌ Ошибка валидации env переменных" in error_msg
