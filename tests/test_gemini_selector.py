
from services.selectors.gemini_selector import GeminiSelector


class DummyGeminiClient:
    def __init__(self):
        self.called_with: dict[str, dict] = {}
        self.marketplace_response: list[dict] = [{"id": 1}]
        self.categories_response: dict[str, list[dict]] = {
            "wildberries": [],
            "ozon": [],
            "general": [],
        }

    def select_and_format_marketplace_news(self, messages, marketplace, top_n):
        self.called_with["marketplace"] = {
            "messages": messages,
            "marketplace": marketplace,
            "top_n": top_n,
        }
        return self.marketplace_response

    def select_three_categories(self, messages, wb_count, ozon_count, general_count):
        self.called_with["categories"] = {
            "messages": messages,
            "wb_count": wb_count,
            "ozon_count": ozon_count,
            "general_count": general_count,
        }
        return self.categories_response


def test_select_marketplace_news_uses_config_default_top_n():
    dummy_client = DummyGeminiClient()
    selector = GeminiSelector(
        dummy_client,
        marketplace_config={
            "ozon": {"top_n": 7},
        },
    )

    result = selector.select_marketplace_news(
        messages=[{"id": 1, "text": "news"}],
        marketplace="ozon",
    )

    assert result == dummy_client.marketplace_response
    assert dummy_client.called_with["marketplace"]["top_n"] == 7


def test_select_categories_passes_custom_counts():
    dummy_client = DummyGeminiClient()
    selector = GeminiSelector(dummy_client, marketplace_config={})

    result = selector.select_categories(
        messages=[{"id": 1}],
        wb_count=3,
        ozon_count=4,
        general_count=2,
    )

    assert result == dummy_client.categories_response
    assert dummy_client.called_with["categories"] == {
        "messages": [{"id": 1}],
        "wb_count": 3,
        "ozon_count": 4,
        "general_count": 2,
    }
