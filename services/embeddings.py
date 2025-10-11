"""Работа с embeddings для проверки дубликатов"""
from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Tuple
from utils.logger import setup_logger

logger = setup_logger(__name__)


class EmbeddingService:
    """Сервис для работы с embeddings"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        Инициализация модели embeddings

        Args:
            model_name: Название модели (поддерживает русский язык)
        """
        logger.info(f"Загрузка модели embeddings: {model_name}")
        self.model = SentenceTransformer(model_name)
        logger.info("Модель embeddings загружена")

    def encode(self, text: str) -> np.ndarray:
        """
        Получить embedding для текста

        Args:
            text: Текст для кодирования

        Returns:
            Numpy array с embedding
        """
        return self.model.encode(text, convert_to_numpy=True)

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """
        Получить embeddings для списка текстов

        Args:
            texts: Список текстов

        Returns:
            Numpy array с embeddings
        """
        return self.model.encode(texts, convert_to_numpy=True, show_progress_bar=True)

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

    def find_duplicates(self, text: str, existing_embeddings: List[Tuple[int, np.ndarray]],
                       threshold: float = 0.85) -> List[Tuple[int, float]]:
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

    def is_duplicate(self, text: str, existing_embeddings: List[Tuple[int, np.ndarray]],
                    threshold: float = 0.85) -> bool:
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
