import asyncio
from types import SimpleNamespace

import pytest

from services.telegram_listener import TelegramListener


class DummyConfig:
    def __init__(self, data: dict):
        self._data = data
        self.telegram_api_id = 123
        self.telegram_api_hash = "hash"
        self.telegram_phone = "+100000000"

    def get(self, path: str, default=None):
        parts = path.split(".")
        value = self._data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value


class DummyDB:
    def __init__(self):
        self.added = []

    def add_channel(self, username, title):
        self.added.append((username, title))

    def get_channel_id(self, username):
        return None

    def close(self):
        pass


class FakeTelethonChannel:
    def __init__(self, channel_id, username, title):
        self.id = channel_id
        self.username = username
        self.title = title
        self.broadcast = True


class FakeClient:
    def __init__(self, channels):
        self._channels = channels

    async def start(self, phone=None):  # pragma: no cover - not used in tests
        return None

    async def get_entity(self, query):
        key = str(query).lstrip("@")
        channel = self._channels.get(key)
        if channel:
            return channel
        # Пытаемся найти по числовому ID
        for entity in self._channels.values():
            if str(entity.id) == str(query):
                return entity
        raise ValueError(f"Channel {query} not found")


def test_manual_mode_loads_channels(monkeypatch):
    channels = {
        "manualchan1": FakeTelethonChannel(1001, "manualchan1", "Manual Channel 1"),
        "manualchan2": FakeTelethonChannel(1002, None, "Manual Channel 2"),
    }
    fake_client = FakeClient(channels)

    monkeypatch.setattr("services.telegram_listener.TelegramClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr("services.telegram_listener.Channel", FakeTelethonChannel)

    config_data = {
        "filters": {"exclude_keywords": []},
        "listener": {
            "mode": "manual",
            "manual_channels": ["manualchan1", "@manualchan2", "manualchan1"],
            "min_message_length": 10,
            "channel_whitelist": [],
            "channel_blacklist": [],
            "healthcheck": {"heartbeat_path": "./logs/test.heartbeat", "interval_seconds": 60},
        },
    }

    listener = TelegramListener(DummyConfig(config_data), DummyDB())
    asyncio.run(listener.load_channels())

    assert listener.mode == "manual"
    assert listener.channel_ids == [1001, 1002]


def test_unknown_mode_falls_back_to_subscriptions(monkeypatch):
    fake_client = SimpleNamespace()
    monkeypatch.setattr("services.telegram_listener.TelegramClient", lambda *args, **kwargs: fake_client)

    config_data = {
        "filters": {"exclude_keywords": []},
        "listener": {
            "mode": "unsupported",
            "manual_channels": [],
            "min_message_length": 10,
            "channel_whitelist": [],
            "channel_blacklist": [],
            "healthcheck": {"heartbeat_path": "./logs/test.heartbeat", "interval_seconds": 60},
        },
    }

    listener = TelegramListener(DummyConfig(config_data), DummyDB())
    assert listener.mode == "subscriptions"


def test_is_channel_allowed_with_whitelist_blacklist(monkeypatch):
    fake_client = SimpleNamespace()
    monkeypatch.setattr("services.telegram_listener.TelegramClient", lambda *args, **kwargs: fake_client)

    config_data = {
        "filters": {"exclude_keywords": []},
        "listener": {
            "mode": "subscriptions",
            "manual_channels": [],
            "min_message_length": 10,
            "channel_whitelist": ["allowed", "ALLOWED2"],
            "channel_blacklist": ["blocked"],
            "healthcheck": {"heartbeat_path": "./logs/test.heartbeat", "interval_seconds": 60},
        },
    }

    listener = TelegramListener(DummyConfig(config_data), DummyDB())

    assert listener._is_channel_allowed("allowed", 100)
    assert listener._is_channel_allowed("ALLOWED2", 101)
    assert not listener._is_channel_allowed("blocked", 102)
    assert not listener._is_channel_allowed("other", 103)
