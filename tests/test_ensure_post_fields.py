"""Tests for ensure_post_fields utility function."""
import pytest

from utils.formatters import ensure_post_fields


class TestEnsurePostFields:
    def test_missing_title_extracts_from_text(self):
        post = {
            "text": "This is a long text message with multiple words that should be truncated",
            "description": "Some description",
        }
        result = ensure_post_fields(post)
        assert result["title"] == "This is a long text message with"
        assert result["description"] == "Some description"

    def test_missing_description_extracts_second_line(self):
        post = {
            "title": "Test Title",
            "text": "First line of text\nSecond line that should become description",
        }
        result = ensure_post_fields(post)
        assert result["title"] == "Test Title"
        assert result["description"] == "Second line that should become description"

    def test_missing_both_fields(self):
        post = {"text": "Single line text message"}
        result = ensure_post_fields(post)
        assert result["title"] == "Single line text message"
        assert len(result["description"]) > 0

    def test_no_text_at_all(self):
        post = {}
        result = ensure_post_fields(post)
        assert result["title"] == "Без заголовка"
        assert result["description"] == "Описание отсутствует"

    def test_preserves_existing_fields(self):
        post = {
            "title": "Existing Title",
            "description": "Existing Description",
            "text": "Some other text",
            "source_link": "https://example.com",
        }
        result = ensure_post_fields(post)
        assert result["title"] == "Existing Title"
        assert result["description"] == "Existing Description"
        assert result["source_link"] == "https://example.com"

    def test_truncates_long_description(self):
        post = {
            "title": "Title",
            "description": "word " * 100,  # ~500 chars
        }
        result = ensure_post_fields(post)
        assert len(result["description"]) <= 253  # 250 + "..."

    def test_multiline_text(self):
        post = {
            "text": "Breaking News: Major Update\n\nThis is the detailed description."
        }
        result = ensure_post_fields(post)
        assert "Breaking" in result["title"]
        assert "detailed description" in result["description"]

    def test_empty_title_treated_as_missing(self):
        post = {"title": "", "text": "Some text here"}
        result = ensure_post_fields(post)
        assert result["title"] == "Some text here"

    def test_empty_description_treated_as_missing(self):
        post = {"title": "Title", "description": "", "text": "First\nSecond line"}
        result = ensure_post_fields(post)
        assert result["description"] == "Second line"

    def test_newsprocessor_delegates_to_utility(self):
        """Verify NewsProcessor._ensure_post_fields delegates to the utility."""
        from services.news_processor import NewsProcessor

        post = {"text": "Test text"}
        result = NewsProcessor._ensure_post_fields(post)
        assert result["title"] == "Test text"
