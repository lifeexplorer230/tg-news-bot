import json
from types import SimpleNamespace

import pytest
from google.api_core import exceptions as google_exceptions
from tenacity import stop_after_attempt, wait_none

from services.gemini_client import GeminiClient


@pytest.fixture
def gemini_client(monkeypatch):
    class DummyModel:
        def __init__(self):
            self._response = SimpleNamespace(text=json.dumps([]))

        def generate_content(self, prompt):
            return self._response

    def dummy_model_factory(model_name):
        return DummyModel()

    monkeypatch.setattr(
        "services.gemini_client.genai.GenerativeModel",
        lambda model_name: dummy_model_factory(model_name),
    )

    client = GeminiClient(api_key="test-key", model_name="test-model")
    retryer = client.select_top_news.retry
    retryer.stop = stop_after_attempt(1)
    retryer.wait = wait_none()
    return client


def _set_raise(client: GeminiClient, exc: Exception) -> None:
    def _raiser(prompt: str):
        raise exc

    client.model.generate_content = _raiser


def test_select_top_news_handles_quota_exceeded(gemini_client):
    _set_raise(gemini_client, google_exceptions.ResourceExhausted("quota exceeded"))

    messages = [{"id": 1, "text": "Новость", "channel_username": "channel"}]

    with pytest.raises(google_exceptions.ResourceExhausted):
        gemini_client.select_top_news(messages, top_n=1)


def test_select_top_news_handles_invalid_api_key(gemini_client):
    _set_raise(gemini_client, google_exceptions.Unauthenticated("invalid key"))
    messages = [{"id": 1, "text": "Новость", "channel_username": "channel"}]

    with pytest.raises(google_exceptions.Unauthenticated):
        gemini_client.select_top_news(messages, top_n=1)


def test_select_top_news_handles_timeout(gemini_client):
    _set_raise(gemini_client, google_exceptions.DeadlineExceeded("timeout"))
    messages = [{"id": 1, "text": "Новость", "channel_username": "channel"}]

    with pytest.raises(google_exceptions.DeadlineExceeded):
        gemini_client.select_top_news(messages, top_n=1)


def test_select_top_news_handles_invalid_json(gemini_client):
    gemini_client.model.generate_content = lambda prompt: SimpleNamespace(text="not-json")
    messages = [{"id": 1, "text": "Новость", "channel_username": "channel"}]

    result = gemini_client.select_top_news(messages, top_n=1)

    assert result == []
