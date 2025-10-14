import asyncio
import time
from collections.abc import Iterable

import numpy as np
import pytest

from services.embeddings import EmbeddingService


class SlowModel:
    def __init__(self, delay_single: float = 0.002, delay_batch: float = 0.002, dim: int = 8):
        self.delay_single = delay_single
        self.delay_batch = delay_batch
        self.dim = dim
        self.calls: list[tuple[str, int]] = []

    def encode(
        self,
        texts,
        *,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
        batch_size: int | None = None,
    ):
        if isinstance(texts, str):
            self.calls.append(("single", 1))
            time.sleep(self.delay_single)
            return np.ones(self.dim, dtype=np.float32)

        if isinstance(texts, Iterable):
            texts_list = list(texts)
        else:
            raise TypeError("Unexpected input type for encode")

        self.calls.append(("batch", len(texts_list)))
        time.sleep(self.delay_batch)
        return np.ones((len(texts_list), self.dim), dtype=np.float32)


@pytest.fixture
def slow_embedding_service(monkeypatch):
    slow_model = SlowModel()
    monkeypatch.setattr(
        "services.embeddings.SentenceTransformer",
        lambda target: slow_model,
    )
    service = EmbeddingService(model_name="slow-model")
    return service, slow_model


def test_encode_batch_much_faster_than_sequential(slow_embedding_service):
    service, slow_model = slow_embedding_service
    texts = [f"Новость {i}" for i in range(100)]

    sequential_start = time.perf_counter()
    for text in texts:
        service.encode(text)
    sequential_duration = time.perf_counter() - sequential_start

    batch_start = time.perf_counter()
    batch_embeddings = service.encode_batch(texts, batch_size=50)
    batch_duration = time.perf_counter() - batch_start

    assert batch_embeddings.shape == (len(texts), slow_model.dim)
    assert sum(1 for call in slow_model.calls if call[0] == "batch") >= 1
    assert batch_duration * 3 < sequential_duration


@pytest.mark.asyncio
async def test_encode_async_works(slow_embedding_service):
    """Тест CR-C5: encode_async работает корректно"""
    service, slow_model = slow_embedding_service
    text = "Тестовое сообщение"

    embedding = await service.encode_async(text)

    assert embedding.shape == (slow_model.dim,)
    assert isinstance(embedding, np.ndarray)


@pytest.mark.asyncio
async def test_encode_batch_async_works(slow_embedding_service):
    """Тест CR-C5: encode_batch_async работает корректно"""
    service, slow_model = slow_embedding_service
    texts = [f"Новость {i}" for i in range(10)]

    embeddings = await service.encode_batch_async(texts, batch_size=5)

    assert embeddings.shape == (len(texts), slow_model.dim)
    assert isinstance(embeddings, np.ndarray)


@pytest.mark.asyncio
async def test_encode_batch_async_faster_than_sequential(slow_embedding_service):
    """Тест CR-C5: batch_async быстрее чем последовательные encode_async"""
    service, slow_model = slow_embedding_service
    texts = [f"Новость {i}" for i in range(50)]

    # Последовательные encode_async
    sequential_start = time.perf_counter()
    for text in texts:
        await service.encode_async(text)
    sequential_duration = time.perf_counter() - sequential_start

    # Batch encode_async
    batch_start = time.perf_counter()
    batch_embeddings = await service.encode_batch_async(texts, batch_size=25)
    batch_duration = time.perf_counter() - batch_start

    assert batch_embeddings.shape == (len(texts), slow_model.dim)
    # Batch должен быть значительно быстрее
    assert batch_duration * 3 < sequential_duration


def test_batch_cosine_similarity_correctness():
    """Тест CR-C5: batch_cosine_similarity дает правильные результаты"""
    # Создаем известные embeddings
    embedding = np.array([1.0, 0.0, 0.0])

    embeddings_matrix = np.array([
        [1.0, 0.0, 0.0],  # Идентичный (similarity = 1.0)
        [0.0, 1.0, 0.0],  # Ортогональный (similarity = 0.0)
        [-1.0, 0.0, 0.0], # Противоположный (similarity = -1.0)
        [0.5, 0.5, 0.0],  # Под углом (similarity ≈ 0.707)
    ])

    similarities = EmbeddingService.batch_cosine_similarity(embedding, embeddings_matrix)

    # Проверяем результаты
    assert len(similarities) == 4
    assert abs(similarities[0] - 1.0) < 0.001
    assert abs(similarities[1] - 0.0) < 0.001
    assert abs(similarities[2] - (-1.0)) < 0.001
    assert abs(similarities[3] - 0.707) < 0.01


def test_batch_cosine_similarity_matches_single():
    """Тест CR-C5: batch_cosine_similarity совпадает с cosine_similarity"""
    # Генерируем случайные embeddings
    np.random.seed(42)
    embedding = np.random.rand(8)
    embeddings_matrix = np.random.rand(10, 8)

    # Batch similarity
    batch_similarities = EmbeddingService.batch_cosine_similarity(embedding, embeddings_matrix)

    # Single similarity для каждого
    single_similarities = []
    for i in range(embeddings_matrix.shape[0]):
        sim = EmbeddingService.cosine_similarity(embedding, embeddings_matrix[i])
        single_similarities.append(sim)

    # Должны совпадать
    assert len(batch_similarities) == len(single_similarities)
    for batch_sim, single_sim in zip(batch_similarities, single_similarities):
        assert abs(batch_sim - single_sim) < 0.001


def test_batch_cosine_similarity_empty_matrix():
    """Тест CR-C5: batch_cosine_similarity обрабатывает пустую матрицу"""
    embedding = np.array([1.0, 0.0, 0.0])
    empty_matrix = np.array([]).reshape(0, 3)

    similarities = EmbeddingService.batch_cosine_similarity(embedding, empty_matrix)

    assert len(similarities) == 0
