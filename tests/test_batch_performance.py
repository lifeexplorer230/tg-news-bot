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
