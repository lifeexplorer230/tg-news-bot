from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Базовый интерфейс для клиентов LLM, отбирающих новости."""

    @abstractmethod
    def select_marketplace_news(
        self,
        messages: list[dict],
        marketplace: str,
        top_n: int,
    ) -> list[dict]:
        """Возвращает отформатированные новости для конкретного маркетплейса."""

    @abstractmethod
    def select_categories(
        self,
        messages: list[dict],
        wb_count: int,
        ozon_count: int,
        general_count: int,
    ) -> dict[str, list[dict]]:
        """Разбивает новости на категории для модерации."""
