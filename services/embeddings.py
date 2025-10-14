"""Работа с embeddings для проверки дубликатов"""

import asyncio
import functools
import threading
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from utils.logger import setup_logger

logger = setup_logger(__name__)

_MODEL_CACHE: dict[str, SentenceTransformer] = {}
_MODEL_LOCK = threading.Lock()


class EmbeddingService:
    """Сервис для работы с embeddings"""

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        *,
        local_path: str | None = None,
        allow_remote_download: bool = True,
        enable_fallback: bool = True,
    ):
        """Создаёт ленивый сервис embeddings.

        Args:
            model_name: Имя модели в Hugging Face sentence-transformers.
            local_path: Путь до локальной копии модели (если есть).
            allow_remote_download: Разрешить скачивание с Hugging Face, если локальной модели нет.
        """
        self.model_name = model_name
        self.local_path = local_path
        self.allow_remote_download = allow_remote_download
        self.enable_fallback = enable_fallback
        self._model: SentenceTransformer | None = None

    def _cache_key(self) -> str:
        return f"{self.model_name}|{self.local_path or ''}"

    def _resolve_model_path(self) -> str:
        if self.local_path:
            local_dir = Path(self.local_path)
            if local_dir.exists():
                return str(local_dir)
            logger.warning("Локальная модель embeddings не найдена по пути %s", local_dir)
        if not self.allow_remote_download:
            if not self.enable_fallback:
                raise FileNotFoundError(
                    "Локальная модель embeddings не найдена, а загрузка из сети запрещена"
                )
            logger.warning(
                "Локальная модель embeddings не найдена, выполняется fallback на удалённую загрузку"
            )
        return self.model_name

    def _ensure_model(self) -> SentenceTransformer:
        if self._model is not None:
            return self._model

        cache_key = self._cache_key()
        if cache_key in _MODEL_CACHE:
            self._model = _MODEL_CACHE[cache_key]
            return self._model

        with _MODEL_LOCK:
            if cache_key in _MODEL_CACHE:
                self._model = _MODEL_CACHE[cache_key]
                return self._model

            model_path = self._resolve_model_path()
            logger.info("Загрузка модели embeddings: %s", model_path)
            model = SentenceTransformer(model_path)
            logger.info("Модель embeddings загружена")
            _MODEL_CACHE[cache_key] = model
            self._model = model
            return self._model

    def encode(self, text: str) -> np.ndarray:
        """
        Получить embedding для текста

        Args:
            text: Текст для кодирования

        Returns:
            Numpy array с embedding
        """
        model = self._ensure_model()
        return model.encode(text, convert_to_numpy=True)

    def encode_batch(
        self,
        texts: list[str] | Iterable[str],
        *,
        batch_size: int | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """
        Получить embeddings для списка текстов

        Args:
            texts: Список текстов
            batch_size: Размер батча для модели (опционально)
            show_progress_bar: Показывать прогресс при батчевом кодировании

        Returns:
            Numpy array с embeddings
        """
        model = self._ensure_model()
        return model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
            batch_size=batch_size,
        )

    async def encode_async(self, text: str) -> np.ndarray:
        """
        Async wrapper для encode (CR-C5)

        Запускает блокирующий encode в thread pool executor чтобы не блокировать async event loop.

        Args:
            text: Текст для кодирования

        Returns:
            Numpy array с embedding
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.encode, text)

    async def encode_batch_async(
        self,
        texts: list[str] | Iterable[str],
        *,
        batch_size: int | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """
        Async wrapper для encode_batch (CR-C5)

        Запускает блокирующий encode_batch в thread pool executor чтобы не блокировать async event loop.

        Args:
            texts: Список текстов
            batch_size: Размер батча для модели (опционально)
            show_progress_bar: Показывать прогресс при батчевом кодировании

        Returns:
            Numpy array с embeddings (shape: [len(texts), embedding_dim])
        """
        loop = asyncio.get_running_loop()
        # Используем partial для передачи именованных аргументов
        func = functools.partial(
            self.encode_batch, batch_size=batch_size, show_progress_bar=show_progress_bar
        )
        return await loop.run_in_executor(None, func, texts)

    @staticmethod
    def cosine_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Вычислить косинусное сходство между двумя embeddings

        Args:
            embedding1: Первый embedding
            embedding2: Второй embedding

        Returns:
            Значение от 0 до 1 (1 = идентичные тексты)
        """
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        return dot_product / (norm1 * norm2)

    def find_duplicates(
        self, text: str, existing_embeddings: list[tuple[int, np.ndarray]], threshold: float = 0.85
    ) -> list[tuple[int, float]]:
        """
        Найти дубликаты для текста среди существующих embeddings

        Args:
            text: Текст для проверки
            existing_embeddings: Список (id, embedding) для сравнения
            threshold: Порог схожести (0.0 - 1.0)

        Returns:
            Список (id, similarity) для дубликатов
        """
        if not existing_embeddings:
            return []

        # Кодируем текст
        text_embedding = self.encode(text)

        # Ищем похожие
        duplicates = []
        for post_id, existing_embedding in existing_embeddings:
            similarity = self.cosine_similarity(text_embedding, existing_embedding)
            if similarity >= threshold:
                duplicates.append((post_id, similarity))

        # Сортируем по убыванию схожести
        duplicates.sort(key=lambda x: x[1], reverse=True)
        return duplicates

    def is_duplicate(
        self, text: str, existing_embeddings: list[tuple[int, np.ndarray]], threshold: float = 0.85
    ) -> bool:
        """
        Проверить, является ли текст дубликатом

        Args:
            text: Текст для проверки
            existing_embeddings: Список существующих embeddings
            threshold: Порог схожести

        Returns:
            True если найден дубликат
        """
        duplicates = self.find_duplicates(text, existing_embeddings, threshold)
        return len(duplicates) > 0
