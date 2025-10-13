"""Тесты для services/gemini_client.py"""

import json

import pytest

import services.gemini_client as gemini_module


class DummyResponse:
    """Простейший ответ, имитирующий объект Gemini."""

    def __init__(self, text: str):
        self.text = text


@pytest.fixture
def gemini_client(monkeypatch):
    """Создать GeminiClient с подменой вызовов к реальному API."""
    responses = []

    class FakeModel:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def generate_content(self, prompt: str):
            if not responses:
                raise AssertionError("Нет подготовленных ответов для Gemini")
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if callable(outcome):
                outcome = outcome(prompt)
            return DummyResponse(outcome)

    monkeypatch.setattr(gemini_module.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(
        gemini_module.genai, "GenerativeModel", lambda model_name: FakeModel(model_name)
    )

    client = gemini_module.GeminiClient(api_key="fake-key", model_name="gemini-mock")
    client._log_api_call = lambda *args, **kwargs: None  # не засоряем вывод логами
    return client, responses


def test_select_top_news_parses_markdown_json(gemini_client):
    client, responses = gemini_client
    responses.append(
        """```json
[
  {\"id\": 1, \"score\": 9, \"reason\": \"Важная новость\"},
  {\"id\": 2, \"score\": 7, \"reason\": \"Дополнительная новость\"}
]
```"""
    )
    messages = [
        {"id": 1, "text": "Новость 1", "channel_username": "ai_news"},
        {"id": 2, "text": "Новость 2", "channel_username": "ai_news"},
    ]

    result = client.select_top_news(messages, top_n=1)

    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["score"] == 9


def test_select_top_news_finds_json_inside_text(gemini_client):
    client, responses = gemini_client
    responses.append('Вот список:\n[\n  {"id": 3, "score": 6, "reason": "Средняя"}\n]\n')
    messages = [
        {"id": 3, "text": "Новость 3", "channel_username": "ai_news"},
    ]

    result = client.select_top_news(messages, top_n=5)

    assert len(result) == 1
    assert result[0]["id"] == 3
    assert result[0]["reason"] == "Средняя"


def test_select_top_news_handles_json_error(gemini_client):
    client, responses = gemini_client
    responses.append("[invalid json")
    messages = [
        {"id": 4, "text": "Новость 4", "channel_username": "ai_news"},
    ]

    result = client.select_top_news(messages)

    assert result == []


def test_select_top_news_uses_custom_prompt(monkeypatch):
    captured_prompt = {}

    class FakeModel:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def generate_content(self, prompt: str):
            captured_prompt["value"] = prompt
            return DummyResponse('[{"id": 1, "score": 9, "reason": "custom"}]')

    monkeypatch.setattr(gemini_module.genai, "configure", lambda api_key: None)
    monkeypatch.setattr(gemini_module.genai, "GenerativeModel", lambda model_name: FakeModel(model_name))

    def loader(key: str) -> str | None:
        if key == "select_top_news":
            return "PROMPT {messages_block}"
        return None

    client = gemini_module.GeminiClient(api_key="key", model_name="model", prompt_loader=loader)
    client._log_api_call = lambda *args, **kwargs: None

    messages = [{"id": 1, "text": "Новость {про тест}", "channel_username": "ai_news"}]
    client.select_top_news(messages, top_n=1)

    assert captured_prompt["value"].startswith("PROMPT ")


def test_format_news_post_adds_source_link(gemini_client):
    client, responses = gemini_client
    responses.append(json.dumps({"title": "Заголовок", "description": "Описание"}))

    formatted = client.format_news_post(
        text="Исходный текст новости",
        channel="ai_news",
        message_link="https://t.me/ai_news/123",
    )

    assert formatted["title"] == "Заголовок"
    assert formatted["description"] == "Описание"
    assert formatted["source_link"] == "https://t.me/ai_news/123"


def test_format_news_post_returns_none_on_error(gemini_client):
    client, responses = gemini_client
    responses.append(Exception("API недоступно"))

    result = client.format_news_post("text", "channel")

    assert result is None


def test_select_and_format_news_enriches_items(gemini_client):
    client, responses = gemini_client
    responses.append(
        """[
  {\"id\": 10, \"score\": 8, \"reason\": \"Важно\", \"title\": \"Новая функция\", \"description\": \"Описание функции\"}
]"""
    )
    messages = [
        {
            "id": 10,
            "text": "Сообщение про новую функцию",
            "channel_username": "ai_news",
            "message_id": 555,
            "channel_id": 42,
        }
    ]

    result = client.select_and_format_news(messages, top_n=3)

    assert len(result) == 1
    item = result[0]
    assert item["source_link"] == "https://t.me/ai_news/555"
    assert item["source_message_id"] == 10
    assert item["source_channel_id"] == 42
    assert item["text"] == "Сообщение про новую функцию"


def test_is_spam_or_ad_detects_spam(gemini_client):
    client, responses = gemini_client
    responses.append("ДА, это реклама")

    assert client.is_spam_or_ad("Узнай секреты за деньги!") is True


def test_is_spam_or_ad_detects_non_spam(gemini_client):
    client, responses = gemini_client
    responses.append("нет, полезно")

    assert client.is_spam_or_ad("Описание релиза Gemini") is False


def test_select_and_format_marketplace_news_enriches_items(gemini_client):
    client, responses = gemini_client
    responses.append(
        """```json
[
  {\"id\": 11, \"score\": 9, \"reason\": \"Важно\", \"title\": \"Ozon снижает комиссии\", \"description\": \"Подробное описание\"}
]
```"""
    )
    messages = [
        {
            "id": 11,
            "text": "Важно для продавцов Ozon",
            "channel_username": "ozon_channel",
            "message_id": 101,
            "channel_id": 7,
        }
    ]

    result = client.select_and_format_marketplace_news(messages, marketplace="ozon", top_n=2)

    assert len(result) == 1
    item = result[0]
    assert item["marketplace"] == "ozon"
    assert item["source_link"] == "https://t.me/ozon_channel/101"
    assert item["text"] == "Важно для продавцов Ozon"


def test_select_and_format_marketplace_news_invalid_json(gemini_client):
    client, responses = gemini_client
    responses.append("Ответ без JSON")

    result = client.select_and_format_marketplace_news(
        [
            {
                "id": 1,
                "text": "Ozon news",
                "channel_username": "ozon",
                "message_id": 1,
                "channel_id": 1,
            }
        ],
        marketplace="ozon",
    )

    assert result == []


def test_select_three_categories_empty_messages(gemini_client):
    client, _ = gemini_client

    result = client.select_three_categories([])

    assert result == {"wildberries": [], "ozon": [], "general": []}


def test_select_three_categories_success(gemini_client):
    client, responses = gemini_client
    responses.append(
        """```json
{
  \"wildberries\": [
    {\"id\": 21, \"score\": 8, \"reason\": \"Изменения\", \"title\": \"Wildberries меняет правила\", \"description\": \"Описание изменений\"}
  ],
  \"ozon\": [
    {\"id\": 22, \"score\": 7, \"reason\": \"Запуск\", \"title\": \"Ozon запускает сервис\", \"description\": \"Подробности запуска\"}
  ],
  \"general\": [
    {\"id\": 23, \"score\": 6, \"reason\": \"Статистика\", \"title\": \"Рынок растет\", \"description\": \"Аналитика рынка\"}
  ]
}
```"""
    )
    messages = [
        {
            "id": 21,
            "text": "Wildberries обновил правила",
            "channel_username": "wb_channel",
            "message_id": 201,
            "channel_id": 5,
        },
        {
            "id": 22,
            "text": "Ozon запустил новый сервис",
            "channel_username": "ozon_channel",
            "message_id": 202,
            "channel_id": 6,
        },
        {
            "id": 23,
            "text": "Общая аналитика рынка маркетплейсов",
            "channel_username": "market_channel",
            "message_id": 203,
            "channel_id": 7,
        },
    ]

    result = client.select_three_categories(messages, wb_count=1, ozon_count=1, general_count=1)

    assert result["wildberries"][0]["category"] == "wildberries"
    assert result["wildberries"][0]["source_link"] == "https://t.me/wb_channel/201"
    assert result["ozon"][0]["category"] == "ozon"
    assert result["general"][0]["category"] == "general"
