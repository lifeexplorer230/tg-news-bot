from services.llm.gemini import GeminiLLMClient


class DummyLegacyGemini:
    def __init__(self):
        self.marketplace_calls: dict[str, dict] = {}
        self.categories_calls: dict[str, dict] = {}
        self.marketplace_result: list[dict] = [{"id": 1}]
        self.categories_result: dict[str, list[dict]] = {
            "wildberries": [],
            "ozon": [],
            "general": [],
        }

    def select_and_format_marketplace_news(self, messages, marketplace, top_n):
        self.marketplace_calls["last"] = {
            "messages": messages,
            "marketplace": marketplace,
            "top_n": top_n,
        }
        return self.marketplace_result

    def select_three_categories(self, messages, wb_count, ozon_count, general_count):
        self.categories_calls["last"] = {
            "messages": messages,
            "wb_count": wb_count,
            "ozon_count": ozon_count,
            "general_count": general_count,
        }
        return self.categories_result


def test_gemini_llm_client_delegates_marketplace_selection():
    legacy = DummyLegacyGemini()
    client = GeminiLLMClient(api_key="fake", model_name="test", client=legacy)  # type: ignore[arg-type]

    result = client.select_marketplace_news(
        messages=[{"id": 1, "text": "msg"}],
        marketplace="ozon",
        top_n=5,
    )

    assert result == legacy.marketplace_result
    assert legacy.marketplace_calls["last"] == {
        "messages": [{"id": 1, "text": "msg"}],
        "marketplace": "ozon",
        "top_n": 5,
    }


def test_gemini_llm_client_delegates_category_selection():
    legacy = DummyLegacyGemini()
    client = GeminiLLMClient(api_key="fake", model_name="test", client=legacy)  # type: ignore[arg-type]

    result = client.select_categories(
        messages=[{"id": 1}],
        wb_count=3,
        ozon_count=4,
        general_count=2,
    )

    assert result == legacy.categories_result
    assert legacy.categories_calls["last"] == {
        "messages": [{"id": 1}],
        "wb_count": 3,
        "ozon_count": 4,
        "general_count": 2,
    }
