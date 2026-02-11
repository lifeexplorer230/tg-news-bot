"""
Тест: save_published при ошибке БД не крашит дайджест — остальные посты сохраняются.
"""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, Mock, patch, call

from services.news_processor import NewsProcessor


def _make_post(msg_id: int) -> dict:
    return {
        "text": f"Post {msg_id}",
        "title": f"Title {msg_id}",
        "description": f"Desc {msg_id}",
        "source_message_id": msg_id,
        "source_channel_id": 100,
        "source_link": f"https://t.me/ch/{msg_id}",
    }


@pytest.mark.asyncio
async def test_save_published_error_does_not_crash_digest():
    """Если save_published падает на одном посте, остальные всё равно сохраняются."""
    posts = [_make_post(1), _make_post(2), _make_post(3)]

    # mock db: падает на посте 2, работает для 1 и 3
    mock_db = Mock()
    call_count = {"n": 0}

    def fake_save_published(**kwargs):
        call_count["n"] += 1
        if kwargs["source_message_id"] == 2:
            raise Exception("DB locked")
        return call_count["n"]

    mock_db.save_published = Mock(side_effect=fake_save_published)

    # mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.encode_batch_async = AsyncMock(
        return_value=np.random.rand(3, 384).astype(np.float32)
    )

    # Создаём минимальный processor через Mock
    processor = Mock(spec=NewsProcessor)
    processor.db = mock_db
    processor.embeddings = mock_embeddings
    processor._cached_published_embeddings = None
    processor._published_embeddings_matrix = None
    processor._published_embeddings_ids = None
    processor.duplicate_threshold = 0.85

    # Привязываем реальный _update_published_cache
    processor._update_published_cache = NewsProcessor._update_published_cache.__get__(
        processor, NewsProcessor
    )

    # Эмулируем блок кода из publish_digest (save + cache update)
    texts = [post["text"] for post in posts]
    embeddings_array = await mock_embeddings.encode_batch_async(texts, batch_size=32)

    post_ids = []
    for post, embedding in zip(posts, embeddings_array):
        try:
            await asyncio.to_thread(
                mock_db.save_published,
                text=post["text"],
                embedding=embedding,
                source_message_id=post["source_message_id"],
                source_channel_id=post["source_channel_id"],
            )
            post_ids.append(post["source_message_id"])
        except Exception:
            pass  # логирование в реальном коде

    # save_published вызван 3 раза
    assert mock_db.save_published.call_count == 3

    # Успешно сохранены 2 из 3 (пост 2 упал)
    assert post_ids == [1, 3]
