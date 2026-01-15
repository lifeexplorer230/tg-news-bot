"""
FIX-DUPLICATE-5: Тесты для фильтрации упоминаний источников

Проблема: Одна новость из разных источников может иметь разные embeddings
из-за упоминания источника в тексте.

Пример:
- "Ozon снизил комиссию" (от Ozon)
- "Wildberries сообщает: Ozon снизил комиссию" (от Wildberries)
- "По данным РБК, Ozon снизил комиссию" (от РБК)

Решение: Удалять/заменять упоминания известных источников перед encoding

Проверяет что:
1. Упоминания источников удаляются из текста
2. Новости из разных источников дают одинаковые embeddings
3. Список источников конфигурируется
"""

import numpy as np
import pytest
from unittest.mock import Mock

from services.embeddings import EmbeddingService, normalize_text_for_embedding


class TestSourceFiltering:
    """Тесты для фильтрации упоминаний источников"""

    def test_remove_source_mentions_basic(self):
        """
        Удаление упоминаний источников из текста

        Пример: "Wildberries сообщает: Ozon снизил комиссию"
        → "Ozon снизил комиссию"
        """
        text = "Wildberries сообщает: Ozon снизил комиссию"
        sources = ["Wildberries", "Ozon", "РБК"]

        # Новая функция для удаления источников
        cleaned = normalize_text_for_embedding(
            text,
            remove_urls=True,
            remove_emoji=True,
            remove_source_mentions=True,
            source_keywords=sources,
        )

        # "Wildberries сообщает:" должно быть удалено
        assert "Wildberries" not in cleaned
        assert "Ozon снизил комиссию" in cleaned

    def test_remove_source_with_common_prefixes(self):
        """
        Удаление источников с типичными префиксами/постфиксами

        Паттерны:
        - "X сообщает:"
        - "По данным X,"
        - "Источник: X"
        - "X заявил:"
        """
        test_cases = [
            ("Wildberries сообщает: новость", "новость"),
            ("По данным РБК, новость", "новость"),
            ("Источник: Коммерсантъ. Новость", "Новость"),
            ("Ozon заявил: новость", "новость"),
            ("Согласно Ведомостям, новость", "новость"),
        ]

        sources = ["Wildberries", "РБК", "Коммерсантъ", "Ozon", "Ведомостям"]

        for original, expected in test_cases:
            cleaned = normalize_text_for_embedding(
                original,
                remove_source_mentions=True,
                source_keywords=sources,
            )
            # Проверяем что упоминание источника удалено
            assert expected.strip() in cleaned.strip(), f"Failed for: {original}"

    def test_same_news_different_sources_produce_similar_embeddings(self):
        """
        Новости из разных источников дают похожие embeddings после фильтрации

        Сценарий: Одна новость "Ozon снизил комиссию" от разных источников
        """
        sources = ["Wildberries", "Ozon", "РБК", "Коммерсантъ", "Ведомости"]

        # Одна новость, разные источники
        texts = [
            "Ozon снизил комиссию для продавцов",  # Оригинал от Ozon
            "Wildberries сообщает: Ozon снизил комиссию для продавцов",  # От WB
            "По данным РБК, Ozon снизил комиссию для продавцов",  # От РБК
        ]

        # Создаём embeddings с фильтрацией источников
        service = EmbeddingService(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            enable_text_normalization=True,
            normalize_remove_sources=True,
            normalize_source_keywords=sources,
        )

        embeddings = [service.encode(text) for text in texts]

        # Все embeddings должны быть очень похожи (similarity > 0.95)
        for i in range(1, len(embeddings)):
            similarity = service.cosine_similarity(embeddings[0], embeddings[i])
            assert similarity > 0.95, (
                f"Новости из разных источников должны быть похожи после фильтрации. "
                f"Text {i}: similarity={similarity:.3f}"
            )

    def test_source_filtering_does_not_affect_content(self):
        """
        Фильтрация источников не удаляет важное содержание

        Если источник упоминается как часть контента (не как префикс),
        он должен остаться.

        Пример: "Ozon и Wildberries снизили комиссии" - оба упоминания остаются
        """
        text = "Ozon и Wildberries снизили комиссии для продавцов"
        sources = ["Ozon", "Wildberries", "РБК"]

        cleaned = normalize_text_for_embedding(
            text,
            remove_source_mentions=True,
            source_keywords=sources,
        )

        # Контекстное упоминание должно остаться (т.к. это часть новости)
        assert "Ozon" in cleaned
        assert "Wildberries" in cleaned
        assert "снизили комиссии" in cleaned

    def test_source_filtering_case_insensitive(self):
        """
        Фильтрация источников без учёта регистра

        "wildberries", "WILDBERRIES", "Wildberries" должны фильтроваться одинаково
        """
        test_cases = [
            "wildberries сообщает: новость",
            "WILDBERRIES сообщает: новость",
            "Wildberries сообщает: новость",
        ]

        sources = ["Wildberries"]

        for text in test_cases:
            cleaned = normalize_text_for_embedding(
                text,
                remove_source_mentions=True,
                source_keywords=sources,
            )
            # Упоминание источника должно быть удалено независимо от регистра
            assert "wildberries" not in cleaned.lower()
            assert "новость" in cleaned

    def test_default_source_list_from_config(self):
        """
        Список источников загружается из конфигурации

        По умолчанию должны быть популярные российские источники:
        - Ozon, Wildberries, Яндекс
        - РБК, Коммерсантъ, Ведомости
        - ТАСС, Интерфакс
        """
        # Этот тест проверяет что дефолтный список источников включён в EmbeddingService
        service = EmbeddingService(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            enable_text_normalization=True,
            normalize_remove_sources=True,
            # normalize_source_keywords не указан - используется дефолт
        )

        # Проверяем что источники из дефолтного списка фильтруются
        text = "РБК сообщает: новость дня"
        embedding1 = service.encode(text)
        embedding2 = service.encode("новость дня")

        similarity = service.cosine_similarity(embedding1, embedding2)
        # Должны быть очень похожи (source фильтруется)
        assert similarity > 0.90

    def test_backward_compatibility_without_source_filtering(self):
        """
        Обратная совместимость: без включения фильтрации источников всё работает как раньше
        """
        service = EmbeddingService(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            enable_text_normalization=True,
            normalize_remove_sources=False,  # Выключено
        )

        text = "Wildberries сообщает: Ozon снизил комиссию"
        embedding = service.encode(text)

        # Должно работать без ошибок
        assert embedding is not None
        assert len(embedding) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
