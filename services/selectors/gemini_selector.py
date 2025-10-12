from services.llm.base import LLMClient


class GeminiSelector:
    """Инкапсулирует обращение к Gemini для различных сценариев отбора новостей."""

    def __init__(self, gemini_client: LLMClient, marketplace_config: dict[str, dict]):
        self._client = gemini_client
        self._marketplace_config = marketplace_config

    def select_marketplace_news(
        self,
        messages: list[dict],
        marketplace: str,
        top_n: int | None = None,
    ) -> list[dict]:
        """Отбирает и форматирует новости для конкретного маркетплейса."""
        marketplace_settings = self._marketplace_config.get(marketplace)
        default_limit = 10
        if marketplace_settings is not None:
            default_limit = getattr(marketplace_settings, "top_n", default_limit)
            if isinstance(marketplace_settings, dict):
                default_limit = marketplace_settings.get("top_n", default_limit)
        limit = top_n or default_limit
        return self._client.select_and_format_marketplace_news(
            messages,
            marketplace=marketplace,
            top_n=limit,
        )

    def select_categories(
        self,
        messages: list[dict],
        wb_count: int = 5,
        ozon_count: int = 5,
        general_count: int = 5,
    ) -> dict[str, list[dict]]:
        """Возвращает подборку новостей по трём категориям."""
        return self._client.select_three_categories(
            messages,
            wb_count=wb_count,
            ozon_count=ozon_count,
            general_count=general_count,
        )
