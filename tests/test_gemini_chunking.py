"""
Тесты для chunking и валидации в Gemini Client (CR-C6)

Проверяем:
- Chunking в select_and_format_marketplace_news
- Chunking в select_three_categories
- Валидацию размера промпта
- Генерацию request_id
- Оценку количества токенов
"""

import pytest

from services.gemini_client import GeminiClient


class MockModel:
    """Mock модель Gemini для тестирования"""

    def __init__(self, response_template=None):
        self.response_template = response_template or self._default_marketplace_response
        self.call_count = 0

    def _default_marketplace_response(self, prompt):
        """Стандартный ответ для маркетплейса"""
        return """[
  {"id": 1, "title": "Новость 1", "description": "Описание 1", "score": 9, "reason": "Важно"},
  {"id": 2, "title": "Новость 2", "description": "Описание 2", "score": 8, "reason": "Полезно"}
]"""

    def _categories_response(self, prompt):
        """Ответ для 3 категорий"""
        return """{
  "wildberries": [{"id": 1, "title": "WB новость", "description": "WB описание", "score": 9, "reason": "Важно"}],
  "ozon": [{"id": 2, "title": "Ozon новость", "description": "Ozon описание", "score": 8, "reason": "Полезно"}],
  "general": [{"id": 3, "title": "Общая новость", "description": "Общее описание", "score": 7, "reason": "Интересно"}]
}"""

    def generate_content(self, prompt):
        """Генерация мокового ответа"""
        self.call_count += 1

        # Определяем какой ответ возвращать по содержимому промпта
        if "select_three_categories" in prompt or "WILDBERRIES" in prompt or "OZON" in prompt:
            response_text = self._categories_response(prompt)
        else:
            response_text = self._default_marketplace_response(prompt)

        class Response:
            def __init__(self, text):
                self.text = text

            def strip(self):
                return self.text

        return Response(response_text)


@pytest.fixture
def gemini_client(monkeypatch):
    """Создаёт GeminiClient с mock моделью"""
    client = GeminiClient(api_key="test-key", model_name="test-model")

    # Патчим _ensure_model чтобы возвращать mock
    mock_model = MockModel()

    def mock_ensure_model():
        return mock_model

    monkeypatch.setattr(client, "_ensure_model", mock_ensure_model)

    return client, mock_model


def test_chunk_list_splits_correctly():
    """Тест CR-C6: _chunk_list разбивает список корректно"""
    items = list(range(100))

    chunks = GeminiClient._chunk_list(items, chunk_size=30)

    assert len(chunks) == 4
    assert len(chunks[0]) == 30
    assert len(chunks[1]) == 30
    assert len(chunks[2]) == 30
    assert len(chunks[3]) == 10


def test_chunk_list_handles_small_list():
    """Тест CR-C6: _chunk_list обрабатывает малый список"""
    items = list(range(10))

    chunks = GeminiClient._chunk_list(items, chunk_size=50)

    assert len(chunks) == 1
    assert len(chunks[0]) == 10


def test_select_marketplace_news_no_chunking_for_small_list(gemini_client):
    """Тест CR-C6: Без chunking для малого списка сообщений"""
    client, mock_model = gemini_client

    messages = [
        {"id": 1, "text": "Новость про Ozon", "channel_username": "test", "channel_id": 1, "message_id": 10},
        {"id": 2, "text": "Ещё новость", "channel_username": "test", "channel_id": 1, "message_id": 11},
    ]

    result = client.select_and_format_marketplace_news(
        messages, marketplace="ozon", top_n=2, chunk_size=50
    )

    # Должен быть только 1 вызов API (без chunking)
    assert mock_model.call_count == 1
    assert len(result) > 0


def test_select_marketplace_news_with_chunking(gemini_client):
    """Тест CR-C6: Chunking срабатывает для большого списка"""
    client, mock_model = gemini_client

    # Создаём 100 сообщений (больше chunk_size=50)
    messages = [
        {
            "id": i,
            "text": f"Новость {i} про Wildberries",
            "channel_username": "test",
            "channel_id": 1,
            "message_id": i + 100,
        }
        for i in range(100)
    ]

    result = client.select_and_format_marketplace_news(
        messages, marketplace="wildberries", top_n=10, chunk_size=50
    )

    # Должно быть 2 вызова API (100 / 50 = 2 чанка)
    assert mock_model.call_count == 2
    # Результат должен быть отсортирован по score и обрезан до top_n=10
    assert len(result) <= 10


def test_select_three_categories_no_chunking_for_small_list(gemini_client):
    """Тест CR-C6: Без chunking для малого списка в 3 категориях"""
    client, mock_model = gemini_client

    messages = [
        {"id": 1, "text": "Новость про WB", "channel_username": "test", "channel_id": 1, "message_id": 10},
        {"id": 2, "text": "Новость про Ozon", "channel_username": "test", "channel_id": 1, "message_id": 11},
        {"id": 3, "text": "Общая новость", "channel_username": "test", "channel_id": 1, "message_id": 12},
    ]

    result = client.select_three_categories(
        messages, wb_count=1, ozon_count=1, general_count=1, chunk_size=50
    )

    # Должен быть только 1 вызов API (без chunking)
    assert mock_model.call_count == 1
    assert "wildberries" in result
    assert "ozon" in result
    assert "general" in result


def test_select_three_categories_with_chunking(gemini_client):
    """Тест CR-C6: Chunking срабатывает для большого списка в 3 категориях"""
    client, mock_model = gemini_client

    # Создаём 120 сообщений (больше chunk_size=50)
    messages = [
        {
            "id": i,
            "text": f"Новость {i}",
            "channel_username": "test",
            "channel_id": 1,
            "message_id": i + 100,
        }
        for i in range(120)
    ]

    result = client.select_three_categories(
        messages, wb_count=5, ozon_count=5, general_count=5, chunk_size=50
    )

    # Должно быть 3 вызова API (120 / 50 = 3 чанка, округление вверх)
    assert mock_model.call_count == 3

    # Результат должен содержать все 3 категории
    assert "wildberries" in result
    assert "ozon" in result
    assert "general" in result

    # Каждая категория должна быть обрезана до своего лимита
    assert len(result["wildberries"]) <= 5
    assert len(result["ozon"]) <= 5
    assert len(result["general"]) <= 5


def test_generate_request_id_is_unique():
    """Тест CR-C6: request_id генерируются уникально"""
    ids = [GeminiClient._generate_request_id() for _ in range(100)]

    # Все ID должны быть уникальными
    assert len(set(ids)) == 100
    # Каждый ID должен быть длиной 8 символов
    assert all(len(id) == 8 for id in ids)


def test_estimate_prompt_tokens():
    """Тест CR-C6: Оценка токенов работает корректно"""
    # ~4 символа = 1 токен
    prompt_100_chars = "a" * 100
    tokens = GeminiClient._estimate_prompt_tokens(prompt_100_chars)
    assert tokens == 25

    prompt_1000_chars = "b" * 1000
    tokens = GeminiClient._estimate_prompt_tokens(prompt_1000_chars)
    assert tokens == 250


def test_validate_prompt_size_accepts_small_prompt(gemini_client, caplog):
    """Тест CR-C6: Валидация пропускает малый промпт без warnings"""
    client, _ = gemini_client

    small_prompt = "a" * 1000  # ~250 токенов

    result = client._validate_prompt_size(small_prompt, max_tokens=30000)

    assert result is True
    # Не должно быть warnings
    assert "слишком большой" not in caplog.text


def test_validate_prompt_size_warns_on_large_prompt(gemini_client, caplog):
    """Тест CR-C6: Валидация предупреждает о большом промпте"""
    client, _ = gemini_client

    # 150000 символов ≈ 37500 токенов (больше 30000)
    large_prompt = "a" * 150000

    result = client._validate_prompt_size(large_prompt, max_tokens=30000)

    assert result is False
    # Должен быть warning
    assert "слишком большой" in caplog.text
    assert "Consider using chunking" in caplog.text


def test_validate_prompt_size_info_on_near_limit(gemini_client, caplog):
    """Тест CR-C6: Валидация показывает info для промпта близкого к лимиту"""
    client, _ = gemini_client

    # 110000 символов ≈ 27500 токенов (>80% от 30000)
    near_limit_prompt = "a" * 110000

    result = client._validate_prompt_size(near_limit_prompt, max_tokens=30000)

    assert result is True
    # Должен быть info log
    assert "близок к лимиту" in caplog.text
