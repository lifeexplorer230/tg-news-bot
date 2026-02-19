"""Gemini LLM адаптер для отбора новостей."""

from services.gemini_client import GeminiClient
from services.llm.base import LLMClient


class GeminiLLMClient(LLMClient):
    """Адаптер вокруг существующего GeminiClient для работы через LLM интерфейс."""

    def __init__(
        self,
        api_key: str,
        model_name: str | None = None,
        prompt_loader=None,
        client: GeminiClient | None = None,
    ):
        self._client = client or GeminiClient(
            api_key=api_key, model_name=model_name, prompt_loader=prompt_loader
        )

    def select_marketplace_news(self, messages, marketplace, top_n):
        return self._client.select_and_format_marketplace_news(
            messages, marketplace=marketplace, top_n=top_n,
        )

    def select_categories(self, messages, wb_count, ozon_count, general_count):
        return self._client.select_three_categories(
            messages, wb_count=wb_count, ozon_count=ozon_count, general_count=general_count,
        )

    def select_by_categories(self, messages, category_counts, chunk_size=50, recently_published=None):
        # GeminiClient не поддерживает recently_published
        return self._client.select_by_categories(messages, category_counts, chunk_size)

    @property
    def raw_client(self) -> GeminiClient:
        return self._client
