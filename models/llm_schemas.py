"""Pydantic schemas для валидации ответов LLM (CR-C6)"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsItemResponse(BaseModel):
    """
    Схема для отдельной новости от Gemini

    Валидирует что ответ содержит все необходимые поля и правильные типы.
    """

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="ID сообщения из БД")
    title: str = Field(..., min_length=5, max_length=500, description="Заголовок новости")
    description: str = Field(
        ..., min_length=10, max_length=2000, description="Описание новости"
    )
    score: int = Field(..., ge=1, le=10, description="Оценка релевантности (1-10)")
    reason: str | None = Field(None, max_length=500, description="Причина отбора")
    source_link: str | None = Field(None, description="Ссылка на источник")
    source_message_id: int | None = Field(None, description="ID исходного сообщения")

    @field_validator("title", "description")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Удаляем лишние пробелы"""
        return v.strip()


class NewsListResponse(BaseModel):
    """
    Схема для списка новостей от Gemini

    Wrapper для массива новостей с дополнительной валидацией.
    """

    model_config = ConfigDict(extra="ignore")

    news: list[NewsItemResponse] = Field(..., description="Список новостей")

    @field_validator("news")
    @classmethod
    def check_not_empty(cls, v: list[NewsItemResponse]) -> list[NewsItemResponse]:
        """Проверяем что список не пустой"""
        if not v:
            raise ValueError("News list cannot be empty")
        return v


class CategoryNewsItem(BaseModel):
    """
    Схема для новости в 3-категорийной системе

    Содержит ID и count для подсчёта релевантности.
    """

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="ID сообщения")
    count: int = Field(..., ge=1, description="Количество упоминаний категории")


class CategoryResponse(BaseModel):
    """
    Схема для одной категории в 3-категорийном ответе

    Содержит массив новостей для данной категории.
    """

    model_config = ConfigDict(extra="ignore")

    category: str = Field(..., description="Название категории")
    news: list[CategoryNewsItem] = Field(..., description="Новости для категории")

    @field_validator("news")
    @classmethod
    def check_news_list(cls, v: list[CategoryNewsItem]) -> list[CategoryNewsItem]:
        """Валидация списка новостей"""
        if len(v) > 100:
            raise ValueError(f"Too many news items in category: {len(v)}")
        return v


class CategoriesResponse(BaseModel):
    """
    Схема для 3-категорийного ответа от Gemini

    Wrapper для списка категорий.
    """

    model_config = ConfigDict(extra="ignore")

    categories: list[CategoryResponse] = Field(..., description="Список категорий")

    @field_validator("categories")
    @classmethod
    def check_categories_count(cls, v: list[CategoryResponse]) -> list[CategoryResponse]:
        """Проверяем что категорий ровно 3"""
        if len(v) != 3:
            raise ValueError(f"Expected 3 categories, got {len(v)}")
        return v


class GeminiValidationResult:
    """
    Результат валидации ответа Gemini

    Содержит либо validated data, либо ошибку.
    """

    def __init__(self, success: bool, data: Any = None, error: str | None = None):
        self.success = success
        self.data = data
        self.error = error

    def __repr__(self) -> str:
        if self.success:
            return f"GeminiValidationResult(success=True, data_type={type(self.data).__name__})"
        return f"GeminiValidationResult(success=False, error={self.error})"
