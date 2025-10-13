import asyncio
from types import SimpleNamespace

from services.status_reporter import StatusReporter


class DummyClient:
    def __init__(self):
        self.messages = []

    async def start(self, **kwargs):
        return None

    async def send_message(self, chat, message):
        self.messages.append((chat, message))

    async def disconnect(self):
        return None


class FakeConfig:
    def __init__(self, data):
        self._data = {
            "telegram": {"session_name": "test_session"},
            **data,
        }
        self.telegram_api_id = 1
        self.telegram_api_hash = "hash"
        self.telegram_phone = "+10000000000"

    def get(self, key, default=None):
        parts = key.split(".")
        value = self._data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value

    def database_settings(self):
        return {}


class DummyDB:
    def get_today_stats(self):
        return {
            "messages_today": 3,
            "processed_today": 2,
            "published_today": 1,
            "unprocessed": 1,
            "active_channels": 5,
            "total_messages": 10,
            "total_published": 4,
        }

    def close(self):
        return None


def test_status_reporter_uses_template(monkeypatch):
    sent = DummyClient()
    monkeypatch.setattr("services.status_reporter.TelegramClient", lambda *args, **kwargs: sent)

    cfg = FakeConfig(
        {
            "status": {
                "chat": "test_chat",
                "bot_name": "Test Bot",
                "timezone": "Europe/Moscow",
                "message_template": "STATUS {bot_name} {date} {messages_today}",
                "bot_token": "",
            }
        }
    )

    reporter = StatusReporter(cfg, db=DummyDB())
    asyncio.run(reporter.send_status())

    assert sent.messages
    chat, message = sent.messages[0]
    assert chat == "test_chat"
    assert message.startswith("STATUS Test Bot")
    assert "3" in message


def test_status_reporter_fallback_on_template_error(monkeypatch):
    sent = DummyClient()
    monkeypatch.setattr("services.status_reporter.TelegramClient", lambda *args, **kwargs: sent)

    cfg = FakeConfig(
        {
            "status": {
                "chat": "test_chat",
                "bot_name": "Test Bot",
                "timezone": "Europe/Moscow",
                "message_template": "Broken {unknown}",
                "bot_token": "",
            }
        }
    )

    reporter = StatusReporter(cfg, db=DummyDB())
    asyncio.run(reporter.send_status())

    assert sent.messages
    _, message = sent.messages[0]
    assert "📊" in message  # default template used
