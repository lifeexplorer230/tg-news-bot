"""Claude LLM адаптер для отбора новостей."""

from services.claude_client import ClaudeNewsClient
from services.llm.base import LLMClient


class ClaudeLLMClient(LLMClient):
    """Адаптер ClaudeNewsClient для работы через LLM интерфейс."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        prompt_loader=None,
    ):
        self._client = ClaudeNewsClient(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            prompt_loader=prompt_loader,
        )

    def select_marketplace_news(self, messages, marketplace, top_n):
        # Claude не используется для marketplace — fallback
        raise NotImplementedError("Use GeminiLLMClient for marketplace news")

    def select_categories(self, messages, wb_count, ozon_count, general_count):
        return self._client.select_by_categories(
            messages,
            {"wildberries": wb_count, "ozon": ozon_count, "general": general_count},
        )

    def rewrite_digest(self, posts, header, footer):
        return self._client.rewrite_digest(posts, header, footer)

    def select_by_categories(self, messages, category_counts, chunk_size=50, recently_published=None, category_descriptions=None):
        return self._client.select_by_categories(
            messages, category_counts, chunk_size, recently_published, category_descriptions
        )

    @property
    def usage(self) -> dict:
        return self._client.usage

    @property
    def raw_client(self) -> ClaudeNewsClient:
        return self._client
