"""
FIX-DUPLICATE-3: Тесты для нормализации текста перед encoding

Проверяет что:
1. Текст нормализуется перед созданием embeddings
2. Удаляются лишние пробелы, переносы строк
3. URL заменяются на маркер (опционально)
4. Эмодзи удаляются (опционально)
5. Нормализация не меняет семантику текста
"""

import numpy as np
import pytest

from services.embeddings import EmbeddingService, normalize_text_for_embedding


class TestTextNormalization:
    """Тесты для функции нормализации текста"""

    def test_normalize_removes_extra_whitespace(self):
        """Удаляет лишние пробелы и переносы строк"""
        text = "Ozon   снизил\n\nкомиссию  для\t\tпродавцов"
        normalized = normalize_text_for_embedding(text)

        # Должны остаться только одинарные пробелы
        assert "  " not in normalized
        assert "\n" not in normalized
        assert "\t" not in normalized
        assert normalized == "Ozon снизил комиссию для продавцов"

    def test_normalize_removes_leading_trailing_spaces(self):
        """Удаляет пробелы в начале и конце"""
        text = "   Текст новости   \n\n"
        normalized = normalize_text_for_embedding(text)

        assert normalized == "Текст новости"
        assert not normalized.startswith(" ")
        assert not normalized.endswith(" ")

    def test_normalize_replaces_urls_with_marker(self):
        """Заменяет URL на маркер [URL]"""
        text = "Смотри https://example.com/news и http://test.ru тут"
        normalized = normalize_text_for_embedding(text, remove_urls=True)

        # URL должны быть заменены на маркер
        assert "https://example.com/news" not in normalized
        assert "http://test.ru" not in normalized
        assert "[URL]" in normalized
        assert normalized == "Смотри [URL] и [URL] тут"

    def test_normalize_keeps_urls_if_disabled(self):
        """Не удаляет URL если remove_urls=False"""
        text = "Ссылка: https://example.com"
        normalized = normalize_text_for_embedding(text, remove_urls=False)

        assert "https://example.com" in normalized

    def test_normalize_removes_emoji(self):
        """Удаляет эмодзи"""
        text = "Отличная новость! 🔥🎉 Ozon снизил комиссию 👍"
        normalized = normalize_text_for_embedding(text, remove_emoji=True)

        # Эмодзи должны быть удалены
        assert "🔥" not in normalized
        assert "🎉" not in normalized
        assert "👍" not in normalized
        assert normalized == "Отличная новость! Ozon снизил комиссию"

    def test_normalize_keeps_emoji_if_disabled(self):
        """Не удаляет эмодзи если remove_emoji=False"""
        text = "Новость 🔥"
        normalized = normalize_text_for_embedding(text, remove_emoji=False)

        assert "🔥" in normalized

    def test_normalize_handles_empty_text(self):
        """Корректно обрабатывает пустой текст"""
        normalized = normalize_text_for_embedding("")
        assert normalized == ""

        normalized = normalize_text_for_embedding("   \n\n  ")
        assert normalized == ""

    def test_normalize_preserves_cyrillic(self):
        """Сохраняет кириллицу"""
        text = "Российский маркетплейс Wildberries"
        normalized = normalize_text_for_embedding(text)

        assert "Российский" in normalized
        assert "маркетплейс" in normalized
        assert "Wildberries" in normalized

    def test_normalize_preserves_numbers(self):
        """Сохраняет числа"""
        text = "Комиссия снижена на 2% с 15 до 13 рублей"
        normalized = normalize_text_for_embedding(text)

        assert "2%" in normalized or "2" in normalized
        assert "15" in normalized
        assert "13" in normalized

    def test_normalize_handles_multiple_urls(self):
        """Корректно обрабатывает несколько URL"""
        text = "Читай на https://site1.com и https://site2.ru/path/to/page"
        normalized = normalize_text_for_embedding(text, remove_urls=True)

        count_url_markers = normalized.count("[URL]")
        assert count_url_markers == 2


class TestEmbeddingServiceNormalization:
    """Тесты интеграции нормализации в EmbeddingService"""

    @pytest.fixture
    def embedding_service(self):
        """EmbeddingService с нормализацией"""
        return EmbeddingService(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            enable_text_normalization=True,
        )

    @pytest.fixture
    def embedding_service_no_norm(self):
        """EmbeddingService без нормализации (для сравнения)"""
        return EmbeddingService(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            enable_text_normalization=False,
        )

    def test_similar_texts_with_different_whitespace_produce_same_embeddings(
        self, embedding_service
    ):
        """
        Тексты с разными пробелами/переносами должны давать идентичные embeddings

        Это главная цель нормализации - устранить технические различия
        """
        text1 = "Ozon снизил комиссию для продавцов на 2%"
        text2 = "Ozon   снизил\n\nкомиссию  для\t\tпродавцов   на  2%"

        embedding1 = embedding_service.encode(text1)
        embedding2 = embedding_service.encode(text2)

        # Косинусное сходство должно быть очень высоким (близко к 1.0)
        similarity = embedding_service.cosine_similarity(embedding1, embedding2)

        assert similarity > 0.99, (
            f"Тексты с разными пробелами должны давать идентичные embeddings, "
            f"получено similarity={similarity:.3f}"
        )

    def test_texts_with_urls_more_similar_after_normalization(
        self, embedding_service, embedding_service_no_norm
    ):
        """
        После удаления URL тексты становятся более похожими

        Сценарий: одна новость с разными ссылками на источники
        """
        text1 = "Ozon снизил комиссию https://source1.com"
        text2 = "Ozon снизил комиссию https://source2.com"

        # Без нормализации - embeddings отличаются из-за разных URL
        emb1_no_norm = embedding_service_no_norm.encode(text1)
        emb2_no_norm = embedding_service_no_norm.encode(text2)
        similarity_no_norm = embedding_service_no_norm.cosine_similarity(
            emb1_no_norm, emb2_no_norm
        )

        # С нормализацией - URL заменены на [URL], embeddings идентичны
        emb1_norm = embedding_service.encode(text1)
        emb2_norm = embedding_service.encode(text2)
        similarity_norm = embedding_service.cosine_similarity(emb1_norm, emb2_norm)

        # С нормализацией similarity должна быть выше
        assert similarity_norm > similarity_no_norm, (
            f"После нормализации тексты должны быть более похожими. "
            f"Без норм: {similarity_no_norm:.3f}, с норм: {similarity_norm:.3f}"
        )
        assert similarity_norm > 0.95, (
            f"После удаления URL тексты должны быть почти идентичны, "
            f"получено similarity={similarity_norm:.3f}"
        )

    def test_normalization_does_not_break_semantic_meaning(self, embedding_service):
        """
        Нормализация не должна ломать семантику текста

        Разные по смыслу тексты должны оставаться разными
        """
        text1 = "Ozon снизил комиссию для продавцов"
        text2 = "Wildberries повысил комиссию для продавцов"

        embedding1 = embedding_service.encode(text1)
        embedding2 = embedding_service.encode(text2)

        similarity = embedding_service.cosine_similarity(embedding1, embedding2)

        # Тексты разные по смыслу (снизил vs повысил, разные маркетплейсы)
        assert similarity < 0.85, (
            f"Разные по смыслу тексты должны иметь низкую similarity, "
            f"получено {similarity:.3f}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
