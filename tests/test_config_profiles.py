from pathlib import Path

import pytest
import yaml

import utils.config as config_module
from utils.config import Config


@pytest.fixture(autouse=True)
def reset_config_singleton():
    yield
    config_module._config_singleton = None


@pytest.fixture
def base_profile_config(tmp_path):
    config_dir = tmp_path / "config"
    profiles_dir = config_dir / "profiles"
    config_dir.mkdir()
    profiles_dir.mkdir()

    base_data = {
        "profile": "marketplace",
        "paths": {
            "data_dir": str(tmp_path / "data"),
            "logs_dir": str(tmp_path / "logs"),
            "sessions_dir": str(tmp_path / "sessions"),
            "db_file_pattern": "{data_dir}/{profile}.db",
            "session_file_pattern": "{sessions_dir}/{profile}",
        },
        "listener": {
            "healthcheck": {
                "heartbeat_path": "{logs_dir}/{profile}.heartbeat",
            }
        },
        "telegram": {},
        "database": {},
        "logging": {
            "file": "{logs_dir}/{profile}.log",
        },
    }
    (config_dir / "base.yaml").write_text(
        yaml.safe_dump(base_data, sort_keys=False),
        encoding="utf-8",
    )

    marketplace_data = {
        "profile": "marketplace",
        "publication": {"channel": "@market"},
        "filters": {"exclude_keywords": ["spam"]},
    }
    (profiles_dir / "marketplace.yaml").write_text(
        yaml.safe_dump(marketplace_data, sort_keys=False),
        encoding="utf-8",
    )

    return config_dir


def _set_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_PHONE", "+100000000")
    monkeypatch.setenv("MY_CHANNEL", "@demo")
    monkeypatch.setenv("MY_PERSONAL_ACCOUNT", "@owner")
    monkeypatch.setenv("GEMINI_API_KEY", "key")


def test_load_config_with_explicit_profile(tmp_path, monkeypatch, base_profile_config):
    _set_env(monkeypatch)
    config_dir = base_profile_config

    cfg = Config(
        profile="marketplace",
        base_path=config_dir / "base.yaml",
        profiles_dir=config_dir / "profiles",
        env_path=tmp_path / ".env",
    )

    assert cfg.profile == "marketplace"
    assert cfg.get("publication.channel") == "@market"

    expected_db = Path(tmp_path) / "data" / "marketplace.db"
    assert Path(cfg.db_path) == expected_db

    expected_session = Path(tmp_path) / "sessions" / "marketplace"
    assert cfg.get("telegram.session_name") == str(expected_session)

    heartbeat = cfg.get("listener.healthcheck.heartbeat_path")
    assert heartbeat == f"{tmp_path}/logs/marketplace.heartbeat"


def test_load_config_uses_profile_from_env(tmp_path, monkeypatch, base_profile_config):
    _set_env(monkeypatch)
    monkeypatch.setenv("PROFILE", "marketplace")
    config_dir = base_profile_config

    cfg = Config(
        base_path=config_dir / "base.yaml",
        profiles_dir=config_dir / "profiles",
        env_path=tmp_path / ".env",
    )

    assert cfg.profile == "marketplace"
    assert cfg.get("filters.exclude_keywords") == ["spam"]
    assert "config" in cfg.__dict__
