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

    @abstractmethod
    def rewrite_digest(
        self,
        posts: list[dict],
        header: str,
        footer: str,
    ) -> str:
        """Переписать дайджест через LLM. По умолчанию возвращает пустую строку (не поддерживается)."""
        return ""

    def select_by_categories(
        self,
        messages: list[dict],
        category_counts: dict[str, int],
        chunk_size: int = 50,
        recently_published: list[str] | None = None,
        category_descriptions: dict[str, str] | None = None,
    ) -> dict[str, list[dict]]:
        """Универсальный отбор новостей по произвольным категориям."""

    @property
    def usage(self) -> dict:
        """Статистика использования (токены, стоимость)."""
        return {}
