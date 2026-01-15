"""Работа с embeddings для проверки дубликатов"""

import asyncio
import functools
import re
import threading
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from utils.logger import setup_logger

logger = setup_logger(__name__)


def normalize_text_for_embedding(
    text: str,
    *,
    remove_urls: bool = True,
    remove_emoji: bool = True,
    remove_source_mentions: bool = False,
    source_keywords: list[str] | None = None,
) -> str:
    """
    FIX-DUPLICATE-3: Нормализация текста перед созданием embeddings
    FIX-DUPLICATE-5: Удаление упоминаний источников для детекции новостей из разных источников

    Цель: Устранить технические различия между текстами, чтобы
    перефразированные дубликаты детектировались лучше.

    Выполняет:
    1. Удаляет лишние пробелы и переносы строк
    2. Заменяет URL на маркер [URL] (опционально)
    3. Удаляет эмодзи (опционально)
    4. Удаляет упоминания источников (опционально) - FIX-DUPLICATE-5
    5. Trim пробелов в начале и конце

    Args:
        text: Текст для нормализации
        remove_urls: Заменять URL на маркер [URL]
        remove_emoji: Удалять эмодзи
        remove_source_mentions: Удалять упоминания источников (FIX-DUPLICATE-5)
        source_keywords: Список источников для удаления (например: ["РБК", "Коммерсантъ"])

    Returns:
        Нормализованный текст

    Example:
        >>> normalize_text_for_embedding("Ozon   снизил\\n\\nкомиссию")
        "Ozon снизил комиссию"
        >>> normalize_text_for_embedding("РБК сообщает: новость", remove_source_mentions=True, source_keywords=["РБК"])
        "новость"
    """
    if not text:
        return ""

    # Шаг 1: Удаляем упоминания источников (FIX-DUPLICATE-5)
    if remove_source_mentions and source_keywords:
        # Паттерны для удаления упоминаний источников:
        # - "X сообщает:"
        # - "По данным X,"
        # - "Источник: X"
        # - "X заявил:"
        # - "Согласно X,"
        # - "X:"
        for source in source_keywords:
            # Экранируем специальные символы regex
            escaped_source = re.escape(source)

            # Паттерны для удаления (case insensitive)
            patterns = [
                rf'{escaped_source}\s+сообщает:?\s*',  # "X сообщает:"
                rf'по данным\s+{escaped_source},?\s*',  # "По данным X,"
                rf'источник:?\s*{escaped_source}\.?\s*',  # "Источник: X"
                rf'{escaped_source}\s+заявил:?\s*',  # "X заявил:"
                rf'согласно\s+{escaped_source},?\s*',  # "Согласно X,"
                rf'{escaped_source}:\s+',  # "X: " (только в начале предложения)
            ]

            for pattern in patterns:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Шаг 2: Заменяем URL на маркер [URL]
    if remove_urls:
        # Regex для URL: http(s)://... или www....
        url_pattern = r'https?://\S+|www\.\S+'
        text = re.sub(url_pattern, '[URL]', text)

    # Шаг 3: Удаляем эмодзи
    if remove_emoji:
        # Regex для эмодзи (Unicode ranges)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        text = emoji_pattern.sub('', text)

    # Шаг 4: Заменяем множественные пробелы и переносы строк на одиночные пробелы
    text = re.sub(r'\s+', ' ', text)

    # Шаг 5: Удаляем пробелы в начале и конце
    text = text.strip()

    return text

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
        enable_text_normalization: bool = True,
        normalize_remove_urls: bool = True,
        normalize_remove_emoji: bool = True,
        normalize_remove_sources: bool = False,
        normalize_source_keywords: list[str] | None = None,
    ):
        """Создаёт ленивый сервис embeddings.

        Args:
            model_name: Имя модели в Hugging Face sentence-transformers.
            local_path: Путь до локальной копии модели (если есть).
            allow_remote_download: Разрешить скачивание с Hugging Face, если локальной модели нет.
            enable_text_normalization: FIX-DUPLICATE-3: Включить нормализацию текста перед encoding
            normalize_remove_urls: Заменять URL на маркер [URL]
            normalize_remove_emoji: Удалять эмодзи
            normalize_remove_sources: FIX-DUPLICATE-5: Удалять упоминания источников
            normalize_source_keywords: Список источников для удаления (по умолчанию - популярные СМИ/маркетплейсы)
        """
        self.model_name = model_name
        self.local_path = local_path
        self.allow_remote_download = allow_remote_download
        self.enable_fallback = enable_fallback
        self._model: SentenceTransformer | None = None

        # FIX-DUPLICATE-3: Параметры нормализации текста
        self.enable_text_normalization = enable_text_normalization
        self.normalize_remove_urls = normalize_remove_urls
        self.normalize_remove_emoji = normalize_remove_emoji

        # FIX-DUPLICATE-5: Параметры фильтрации источников
        self.normalize_remove_sources = normalize_remove_sources
        # Дефолтный список популярных источников (российские СМИ и маркетплейсы)
        self.normalize_source_keywords = normalize_source_keywords or [
            "Ozon", "Wildberries", "Яндекс",
            "РБК", "Коммерсантъ", "Ведомости",
            "ТАСС", "Интерфакс", "РИА Новости",
            "Лента.ру", "Газета.ру",
        ]

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
        # FIX-DUPLICATE-3: Применяем нормализацию перед encoding
        # FIX-DUPLICATE-5: Включая фильтрацию источников
        if self.enable_text_normalization:
            text = normalize_text_for_embedding(
                text,
                remove_urls=self.normalize_remove_urls,
                remove_emoji=self.normalize_remove_emoji,
                remove_source_mentions=self.normalize_remove_sources,
                source_keywords=self.normalize_source_keywords,
            )
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
        # FIX-DUPLICATE-3: Применяем нормализацию к каждому тексту перед encoding
        # FIX-DUPLICATE-5: Включая фильтрацию источников
        if self.enable_text_normalization:
            texts = [
                normalize_text_for_embedding(
                    text,
                    remove_urls=self.normalize_remove_urls,
                    remove_emoji=self.normalize_remove_emoji,
                    remove_source_mentions=self.normalize_remove_sources,
                    source_keywords=self.normalize_source_keywords,
                )
                for text in texts
            ]
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

        # QA-5: Защита от деления на ноль при нулевых нормах
        if norm1 == 0 or norm2 == 0:
            logger.debug("cosine_similarity: получен embedding с нулевой нормой, возвращаем 0.0")
            return 0.0

        return dot_product / (norm1 * norm2)

    @staticmethod
    def batch_cosine_similarity(
        embedding: np.ndarray, embeddings_matrix: np.ndarray
    ) -> np.ndarray:
        """
        Вычислить косинусное сходство между одним embedding и массивом embeddings (CR-C5)

        Использует numpy векторизацию для ускорения вычислений O(1) вместо O(N).

        Args:
            embedding: Embedding для сравнения (1D array, shape: [embedding_dim])
            embeddings_matrix: Матрица embeddings (2D array, shape: [n_embeddings, embedding_dim])

        Returns:
            Array со значениями similarity (shape: [n_embeddings])
        """
        if embeddings_matrix.shape[0] == 0:
            return np.array([])

        # Нормализуем query embedding
        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm == 0:
            return np.zeros(embeddings_matrix.shape[0])

        # Нормализуем все embeddings в матрице
        norms = np.linalg.norm(embeddings_matrix, axis=1)
        # Избегаем деления на ноль
        norms = np.where(norms == 0, 1, norms)

        # Векторизованное вычисление dot products
        dot_products = np.dot(embeddings_matrix, embedding)

        # Косинусное сходство = dot_product / (norm1 * norm2)
        similarities = dot_products / (norms * embedding_norm)

        return similarities

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
