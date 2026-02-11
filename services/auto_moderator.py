"""
Модуль автоматической модерации новостей.

Заменяет ручную модерацию на полностью автоматический процесс:
1. Финальная дедупликация отобранных новостей
2. Отбор топ-N по score
3. Публикация без участия человека
"""

import asyncio
from dataclasses import dataclass

import numpy as np

from services.embeddings import EmbeddingService
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModerationResult:
    """Результат автоматической модерации"""
    approved_posts: list[dict]
    rejected_posts: list[dict]
    rejection_reasons: dict[int, str]  # source_message_id -> reason


class AutoModerator:
    """
    Автоматический модератор новостей.

    Выполняет финальную проверку перед публикацией:
    - Дедупликация по embeddings
    - Отбор топ-N по score
    - Валидация обязательных полей
    """

    def __init__(
        self,
        embeddings_service: EmbeddingService,
        *,
        duplicate_threshold: float = 0.85,
        final_top_n: int = 10,
    ):
        """
        Args:
            embeddings_service: Сервис для работы с embeddings
            duplicate_threshold: Порог схожести для дедупликации (0.85 = почти идентичные)
            final_top_n: Финальное количество новостей в дайджесте
        """
        self.embeddings = embeddings_service
        self.duplicate_threshold = duplicate_threshold
        self.final_top_n = final_top_n

    async def moderate(
        self,
        posts: list[dict],
        *,
        top_n: int | None = None,
    ) -> ModerationResult:
        """
        Автоматическая модерация списка новостей.

        Args:
            posts: Список новостей от Gemini с полями:
                   {title, description, score, source_message_id, text, ...}
            top_n: Количество новостей для публикации (по умолчанию self.final_top_n)

        Returns:
            ModerationResult с одобренными и отклонёнными новостями
        """
        target_count = top_n or self.final_top_n
        rejection_reasons: dict[int, str] = {}

        if not posts:
            logger.warning("AutoModerator: получен пустой список новостей")
            return ModerationResult(
                approved_posts=[],
                rejected_posts=[],
                rejection_reasons={},
            )

        logger.info(f"🤖 AutoModerator: начинаю модерацию {len(posts)} новостей (цель: {target_count})")

        # ШАГ 1: Валидация обязательных полей
        valid_posts = []
        for post in posts:
            post_id = post.get("source_message_id", id(post))

            if not post.get("title"):
                rejection_reasons[post_id] = "missing_title"
                logger.debug(f"Отклонено: нет title (id={post_id})")
                continue

            if not post.get("description"):
                rejection_reasons[post_id] = "missing_description"
                logger.debug(f"Отклонено: нет description (id={post_id})")
                continue

            if not post.get("text"):
                rejection_reasons[post_id] = "missing_text"
                logger.debug(f"Отклонено: нет text для embeddings (id={post_id})")
                continue

            valid_posts.append(post)

        if not valid_posts:
            logger.warning("AutoModerator: все новости отклонены на этапе валидации")
            return ModerationResult(
                approved_posts=[],
                rejected_posts=posts,
                rejection_reasons=rejection_reasons,
            )

        logger.info(f"✅ Валидация: {len(valid_posts)}/{len(posts)} прошли проверку полей")

        # ШАГ 2: Сортировка по score (от большего к меньшему)
        valid_posts.sort(key=lambda x: x.get("score", 0), reverse=True)

        # ШАГ 3: Финальная дедупликация
        unique_posts, duplicates = await self._deduplicate(valid_posts)

        for dup in duplicates:
            post_id = dup.get("source_message_id", id(dup))
            rejection_reasons[post_id] = "duplicate_in_final"

        logger.info(f"✅ Дедупликация: {len(unique_posts)} уникальных, {len(duplicates)} дубликатов")

        # ШАГ 4: Отбор топ-N
        approved = unique_posts[:target_count]
        rejected_by_limit = unique_posts[target_count:]

        for post in rejected_by_limit:
            post_id = post.get("source_message_id", id(post))
            rejection_reasons[post_id] = "exceeded_top_n_limit"

        # Собираем все отклонённые
        all_rejected = [p for p in posts if p not in approved]

        logger.info(
            f"🎯 AutoModerator завершён: {len(approved)} одобрено, "
            f"{len(all_rejected)} отклонено"
        )

        # Логируем финальный список
        for idx, post in enumerate(approved, 1):
            logger.debug(
                f"  {idx}. [{post.get('score', 0)}/10] {post.get('title', '')[:50]}..."
            )

        return ModerationResult(
            approved_posts=approved,
            rejected_posts=all_rejected,
            rejection_reasons=rejection_reasons,
        )

    async def _deduplicate(
        self,
        posts: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """
        Дедупликация новостей по embeddings.

        Проверяет каждую новость на схожесть с уже принятыми.

        Args:
            posts: Список новостей (уже отсортированный по score)

        Returns:
            Tuple (unique_posts, duplicates)
        """
        if not posts:
            return [], []

        unique: list[dict] = []
        duplicates: list[dict] = []
        seen_embeddings: list[np.ndarray] = []

        # Создаём embeddings для всех постов за один batch-вызов
        # Используем оригинальный text для точной дедупликации (LLM-генерированные title/description могут отличаться)
        texts = [
            post.get('text', f"{post.get('title', '')} {post.get('description', '')}")
            for post in posts
        ]

        embeddings_array = await self.embeddings.encode_batch_async(texts, batch_size=32)

        for post, embedding in zip(posts, embeddings_array):
            if not seen_embeddings:
                # Первый пост всегда уникален
                unique.append(post)
                seen_embeddings.append(embedding)
                continue

            # Проверяем similarity с уже принятыми
            seen_matrix = np.array(seen_embeddings)
            similarities = self.embeddings.batch_cosine_similarity(embedding, seen_matrix)
            max_similarity = np.max(similarities) if len(similarities) > 0 else 0.0

            if max_similarity >= self.duplicate_threshold:
                # Найден дубликат
                duplicates.append(post)
                duplicate_idx = int(np.argmax(similarities))
                logger.debug(
                    f"🔍 Дубликат: '{post.get('title', '')[:40]}...' "
                    f"похожа на #{duplicate_idx + 1} (sim={max_similarity:.3f})"
                )
            else:
                # Уникальная новость
                unique.append(post)
                seen_embeddings.append(embedding)

        return unique, duplicates

    @staticmethod
    def ensure_post_fields(post: dict) -> dict:
        """
        Гарантирует наличие обязательных полей в посте.

        Если title или description отсутствуют, извлекает из text.

        Args:
            post: Словарь с данными поста

        Returns:
            Пост с гарантированными полями title, description
        """
        # Проверяем title
        if not post.get("title"):
            text = post.get("text", "")
            if text:
                lines = text.split("\n", 1)
                first_line = lines[0].strip()
                words = first_line.split()
                post["title"] = " ".join(words[:7]) if len(words) > 7 else first_line
            else:
                post["title"] = "Без заголовка"

        # Проверяем description
        if not post.get("description"):
            text = post.get("text", "")
            if text:
                lines = text.split("\n", 1)
                if len(lines) > 1:
                    post["description"] = lines[1].strip()[:200]
                else:
                    words = text.split()
                    post["description"] = " ".join(words[7:])[:200] if len(words) > 7 else text[:200]
            else:
                post["description"] = "Описание отсутствует"

        return post
