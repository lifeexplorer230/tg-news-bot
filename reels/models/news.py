"""
Модели данных для новостей

Содержит структуры данных для входных новостей и обогащенных новостей.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class News(BaseModel):
    """Входная новость из БД ТНБ"""

    id: str = Field(..., description="ID новости из базы данных")
    title: str = Field(..., description="Заголовок новости")
    summary: str = Field(..., description="Краткое описание новости")
    source: str = Field(..., description="Источник новости (Telegram канал)")
    url: Optional[str] = Field(None, description="Ссылка на оригинал (опционально)")
    published_date: str = Field(..., description="Дата публикации (ISO 8601)")
    category: Optional[str] = Field(None, description="Категория новости (ai, marketplace, etc.)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "news_001",
                "title": "Новая AI модель от OpenAI",
                "summary": "Компания OpenAI представила GPT-5...",
                "source": "@techcrunch",
                "url": "https://example.com/news/1",
                "published_date": "2025-10-20T10:00:00Z",
                "category": "ai"
            }
        }


class Enrichment(BaseModel):
    """Обогащение новости от Perplexity API"""

    additional_context: str = Field(
        ...,
        description="Дополнительный контекст и детали события"
    )
    key_facts: List[str] = Field(
        ...,
        min_length=3,
        max_length=10,
        description="Ключевые факты (5-7 пунктов)"
    )
    background: str = Field(
        ...,
        description="Предыстория события"
    )
    implications: str = Field(
        ...,
        description="Возможные последствия и влияние"
    )
    related_topics: List[str] = Field(
        ...,
        description="Связанные темы для дальнейшего изучения"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "additional_context": "Детальный контекст о GPT-5...",
                "key_facts": [
                    "GPT-5 на 40% быстрее предшественника",
                    "Поддержка мультимодальности",
                    "Стоимость использования снижена вдвое"
                ],
                "background": "История развития GPT моделей...",
                "implications": "Влияние на индустрию AI...",
                "related_topics": ["AI", "Large Language Models", "OpenAI"]
            }
        }


class ProcessingMetadata(BaseModel):
    """Метаданные обработки через Perplexity"""

    processed_at: str = Field(
        ...,
        description="Timestamp обработки (ISO 8601)"
    )
    tokens_used: int = Field(
        ...,
        ge=0,
        description="Количество токенов использованных API"
    )
    model: str = Field(
        ...,
        description="Модель Perplexity использованная для обработки"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "processed_at": "2025-10-20T12:00:00Z",
                "tokens_used": 500,
                "model": "sonar-pro"
            }
        }


class EnrichedNews(BaseModel):
    """Новость обогащенная через Perplexity API"""

    # Базовые поля из исходной новости
    id: str = Field(..., description="ID исходной новости")
    title: str = Field(..., description="Заголовок новости")
    summary: str = Field(..., description="Краткое описание")
    source: str = Field(..., description="Источник")

    # Обогащение от Perplexity
    enrichment: Enrichment = Field(
        ...,
        description="Обогащенные данные от Perplexity API"
    )

    # Метаданные обработки
    processing_metadata: ProcessingMetadata = Field(
        ...,
        description="Метаданные обработки"
    )

    @classmethod
    def from_news(
        cls,
        news: News,
        enrichment: Enrichment,
        metadata: ProcessingMetadata
    ) -> "EnrichedNews":
        """
        Создать EnrichedNews из News и данных обогащения

        Args:
            news: Исходная новость
            enrichment: Данные обогащения
            metadata: Метаданные обработки

        Returns:
            EnrichedNews объект
        """
        return cls(
            id=news.id,
            title=news.title,
            summary=news.summary,
            source=news.source,
            enrichment=enrichment,
            processing_metadata=metadata
        )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "news_001",
                "title": "Новая AI модель от OpenAI",
                "summary": "Компания OpenAI представила GPT-5...",
                "source": "@techcrunch",
                "enrichment": {
                    "additional_context": "Детальный контекст...",
                    "key_facts": ["Факт 1", "Факт 2", "Факт 3"],
                    "background": "Предыстория...",
                    "implications": "Последствия...",
                    "related_topics": ["AI", "GPT"]
                },
                "processing_metadata": {
                    "processed_at": "2025-10-20T12:00:00Z",
                    "tokens_used": 500,
                    "model": "sonar-pro"
                }
            }
        }
