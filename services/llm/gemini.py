from services.gemini_client import GeminiClient
from services.llm.base import LLMClient


class GeminiLLMClient(LLMClient):
    """Адаптер вокруг существующего GeminiClient для работы через LLM интерфейс."""

    def __init__(
        self,
        api_key: str,
        model_name: str | None = None,
        client: GeminiClient | None = None,
    ):
        self._client = client or GeminiClient(api_key=api_key, model_name=model_name)

    def select_marketplace_news(
        self,
        messages: list[dict],
        marketplace: str,
        top_n: int,
    ) -> list[dict]:
        return self._client.select_and_format_marketplace_news(
            messages,
            marketplace=marketplace,
            top_n=top_n,
        )

    def select_categories(
        self,
        messages: list[dict],
        wb_count: int,
        ozon_count: int,
        general_count: int,
    ) -> dict[str, list[dict]]:
        return self._client.select_three_categories(
            messages,
            wb_count=wb_count,
            ozon_count=ozon_count,
            general_count=general_count,
        )

    @property
    def raw_client(self) -> GeminiClient:
        """Возвращает оригинальный GeminiClient при необходимости."""
        return self._client
