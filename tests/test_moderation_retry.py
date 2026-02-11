"""Tests for _wait_for_moderation_response_retry — bounded retry loop."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.news_processor import NewsProcessor


def _make_processor():
    """Create a minimal NewsProcessor with mocked dependencies."""
    config = MagicMock()
    config.get.return_value = None
    config.profile = "test"
    config.db_path = ":memory:"
    config.telegram_api_id = 1
    config.telegram_api_hash = "hash"
    config.telegram_phone = "+10000000000"
    db = MagicMock()
    processor = object.__new__(NewsProcessor)
    processor.config = config
    processor.db = db
    return processor


class FakeConv:
    """Fake conversation that returns pre-defined responses."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._sent: list[str] = []

    async def get_response(self, timeout=None):
        if not self._responses:
            raise TimeoutError("No more responses")
        text = self._responses.pop(0)
        return SimpleNamespace(message=text)

    async def send_message(self, msg: str):
        self._sent.append(msg)


class TestModerationRetry:
    """Tests for bounded retry in moderation response."""

    def test_valid_input_returns_ids(self):
        proc = _make_processor()
        conv = FakeConv(["1 3 5"])
        result = asyncio.run(proc._wait_for_moderation_response_retry(conv, total_posts=5))
        assert result == [1, 3, 5]

    def test_cancel_returns_none(self):
        proc = _make_processor()
        conv = FakeConv(["отмена"])
        result = asyncio.run(proc._wait_for_moderation_response_retry(conv, total_posts=5))
        assert result is None

    def test_publish_all_returns_empty(self):
        proc = _make_processor()
        conv = FakeConv(["0"])
        result = asyncio.run(proc._wait_for_moderation_response_retry(conv, total_posts=5))
        assert result == []

    def test_invalid_then_valid(self):
        proc = _make_processor()
        conv = FakeConv(["abc", "2 4"])
        result = asyncio.run(proc._wait_for_moderation_response_retry(conv, total_posts=5))
        assert result == [2, 4]
        assert any("Не удалось распознать" in msg for msg in conv._sent)

    def test_max_retries_exceeded(self):
        proc = _make_processor()
        # 3 invalid inputs with max_retries=3
        conv = FakeConv(["abc", "xyz", "!!!"])
        result = asyncio.run(
            proc._wait_for_moderation_response_retry(conv, total_posts=5, max_retries=3)
        )
        assert result is None
        assert any("Превышено количество попыток" in msg for msg in conv._sent)

    def test_no_stack_overflow_on_many_retries(self):
        """Ensure no RecursionError even with many invalid inputs."""
        proc = _make_processor()
        conv = FakeConv(["bad"] * 10)
        result = asyncio.run(
            proc._wait_for_moderation_response_retry(conv, total_posts=5, max_retries=10)
        )
        assert result is None

    def test_out_of_range_numbers_ignored(self):
        proc = _make_processor()
        conv = FakeConv(["99 100", "2"])
        result = asyncio.run(
            proc._wait_for_moderation_response_retry(conv, total_posts=5, max_retries=3)
        )
        assert result == [2]
