"""Универсальный процессор новостей с поддержкой категорий"""

import asyncio
from datetime import datetime, timedelta

import numpy as np
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from database.db import Database
from models.category import Category
from services.embeddings import EmbeddingService
from services.gemini_client import GeminiClient
from services.llm import create_llm_client, LLMClient
from services.auto_moderator import AutoModerator, ModerationResult
from utils.config import Config
from utils.constants import NUMBER_EMOJIS
from utils.formatters import ensure_post_fields
from utils.logger import get_logger
from utils.advanced_rate_limiter import MultiLevelRateLimiter, AdaptiveRateLimiter
from utils.telegram_helpers import safe_connect
from utils.timezone import now_msk

logger = get_logger(__name__)


class NewsProcessor:
    """Универсальный процессор новостей с поддержкой категорий"""

    # Константы для работы с Telegram API
    TELEGRAM_MESSAGE_LIMIT = 4096  # Максимальная длина сообщения в Telegram
    PREVIEW_SAFETY_MARGIN = 50     # Запас символов для безопасности
    MAX_MESSAGE_SIZE = 100000      # 100KB - максимальный размер входящего сообщения (security)

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path, **config.database_settings())
        self._embedding_service: EmbeddingService | None = None
        self._gemini_client: GeminiClient | None = None
        self._llm_client: LLMClient | None = None

        # Security: Многоуровневый rate limiter для защиты от Telegram API limits
        # Включает global limits, burst protection, per-chat limits
        base_limiter = MultiLevelRateLimiter()
        self._rate_limiter = AdaptiveRateLimiter(base_limiter)

        # Кэш для оптимизации (CR-H1)
        self._cached_published_embeddings: list[tuple[int, any]] | None = None
        # QA-7: _cached_base_messages удалён как мёртвый код (не используется)

        # FIX-DUPLICATE-1: TTL-based cache invalidation для предотвращения дубликатов между запусками
        self._cache_timestamp: datetime | None = None
        self._cache_ttl_seconds: int = config.get("cache.ttl_seconds", 1800)  # 30 минут по умолчанию

        # QA-4: Кэш матрицы embeddings для оптимизации дедупликации O(N²) → O(N)
        self._published_embeddings_matrix: np.ndarray | None = None
        self._published_embeddings_ids: list[int] | None = None

        self._embedding_model_name = config.get(
            "embeddings.model", "paraphrase-multilingual-MiniLM-L12-v2"
        )
        self._embedding_local_path = config.get("embeddings.local_path")
        self._embedding_allow_remote = config.get("embeddings.allow_remote_download", True)
        self._embedding_enable_fallback = config.get("embeddings.enable_fallback", True)
        self._gemini_model_name = config.get("gemini.model", "gemini-1.5-flash")

        self.global_exclude_keywords = [
            keyword.lower() for keyword in config.get("filters.exclude_keywords", []) if keyword
        ]

        # U4: Backwards compatibility - поддержка обоих ключей (categories и marketplaces)
        raw_marketplaces = config.get("categories") or config.get("marketplaces", [])
        if isinstance(raw_marketplaces, dict):
            raw_marketplaces = [
                {
                    "name": name,
                    **(raw_marketplaces[name] or {}),
                }
                for name in raw_marketplaces
            ]

        self.categories: dict[str, Category] = {}
        for mp_cfg in raw_marketplaces:
            if not isinstance(mp_cfg, dict):
                continue
            data = dict(mp_cfg)
            data.setdefault("enabled", True)
            try:
                category = Category(**data)
            except TypeError as exc:
                logger.error(f"Некорректная конфигурация категории {mp_cfg}: {exc}")
                continue
            category.combined_exclude_keywords_lower = list(
                dict.fromkeys(category.exclude_keywords_lower + self.global_exclude_keywords)
            )
            self.categories[category.name] = category

        if not self.categories:
            logger.warning("В конфигурации не найдено ни одной категории")

        self.all_exclude_keywords_lower = set(self.global_exclude_keywords)
        for category in self.categories.values():
            self.all_exclude_keywords_lower.update(category.combined_exclude_keywords_lower)

        self.category_names = list(self.categories.keys())

        default_channel = next(
            (mp.target_channel for mp in self.categories.values() if mp.target_channel),
            None,
        )

        self.all_digest_enabled = config.get("channels.all_digest.enabled", True)
        self.all_digest_channel = config.get(
            "channels.all_digest.target_channel",
            default_channel,
        )
        counts_config = config.get("channels.all_digest.category_counts", {})
        # Динамически читаем категории из конфига (универсальная система)
        # Поддерживает любые категории, не только marketplace-специфичные
        self.all_digest_counts = dict(counts_config) if counts_config else {}
        descriptions_config = config.get("channels.all_digest.category_descriptions", {})
        self.all_digest_descriptions = dict(descriptions_config) if descriptions_config else {}

        self.publication_header_template = config.get(
            "publication.header_template",
            "📰 Главные новости за {date}",
        )
        self.publication_footer_template = config.get("publication.footer_template", "")
        self.publication_preview_channel = config.get("publication.preview_channel")
        self.publication_notify_account = config.get("publication.notify_account")

        # FIX-DUPLICATE-2: Снижен порог с 0.85 до 0.78 для лучшей детекции перефразированных дубликатов
        self.duplicate_threshold = config.get("processor.duplicate_threshold", 0.78)

        # FIX-DUPLICATE-4: DBSCAN clustering для лучшей детекции кластеров дубликатов
        self.use_dbscan = config.get("processor.use_dbscan", False)  # По умолчанию выключен (backwards compatibility)
        self.dbscan_eps = config.get("processor.dbscan_eps", 0.22)  # eps = 1 - similarity_threshold (1 - 0.78 = 0.22)
        self.dbscan_min_samples = config.get("processor.dbscan_min_samples", 2)  # Минимум 2 точки для кластера

        # FIX-DUPLICATE-6: Настраиваемое временное окно для поиска дубликатов
        self.duplicate_time_window_days = config.get("processor.duplicate_time_window_days", 60)  # 60 дней по умолчанию

        self.processor_top_n = config.get("processor.top_n", 10)
        self.processor_exclude_count = config.get("processor.exclude_count", 5)
        if not isinstance(self.processor_top_n, int) or self.processor_top_n <= 0:
            logger.warning(
                "Некорректное значение processor.top_n=%s, используем 10",
                self.processor_top_n,
            )
            self.processor_top_n = 10
        if not isinstance(self.processor_exclude_count, int) or self.processor_exclude_count < 0:
            logger.warning(
                "Некорректное значение processor.exclude_count=%s, используем 5",
                self.processor_exclude_count,
            )
            self.processor_exclude_count = 5
        # Настройки модерации
        # auto_moderation: True = полностью автоматически, False = с ручным подтверждением
        self.auto_moderation = config.get("moderation.auto", True)
        self.moderation_enabled = config.get("moderation.enabled", True)
        self.moderation_timeout_hours = config.get("moderation.timeout_hours", 2)
        # final_top_n: финальное количество новостей после модерации (по умолчанию 10)
        self.final_top_n = config.get("moderation.final_top_n", 10)

        # Кэш для AutoModerator
        self._auto_moderator: AutoModerator | None = None

    @property
    def auto_moderator(self) -> AutoModerator:
        """Ленивая инициализация автомодератора"""
        if self._auto_moderator is None:
            self._auto_moderator = AutoModerator(
                embeddings_service=self.embeddings,
                duplicate_threshold=self.duplicate_threshold,
                final_top_n=self.final_top_n,  # Используем отдельную настройку (по умолчанию 10)
            )
        return self._auto_moderator

    @property
    def embeddings(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(
                model_name=self._embedding_model_name,
                local_path=self._embedding_local_path,
                allow_remote_download=self._embedding_allow_remote,
                enable_fallback=self._embedding_enable_fallback,
            )
        return self._embedding_service

    @property
    def gemini(self) -> GeminiClient:
        if self._gemini_client is None:
            self._gemini_client = GeminiClient(
                api_key=self.config.gemini_api_key,
                model_name=self._gemini_model_name,
                prompt_loader=self.config.load_prompt,
            )
        return self._gemini_client

    @property
    def llm_client(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = create_llm_client(self.config)
        return self._llm_client

    # СТАРАЯ СИСТЕМА УДАЛЕНА: метод process_category() больше не используется
    # Используется только 3-категорийная система через process_all_categories()

    def _filter_by_keywords(
        self, messages: list[dict], keywords_lower: list[str], exclude_keywords_lower: list[str]
    ) -> tuple[list[dict], dict[int, str]]:
        """
        Фильтрация сообщений по ключевым словам

        Returns:
            Tuple of (filtered_messages, rejected_reasons)
            where rejected_reasons maps message_id -> rejection_reason
        """
        filtered = []
        rejected = {}

        for msg in messages:
            text_lower = msg["text"].lower()

            # Проверяем исключающие слова
            if exclude_keywords_lower and any(
                exclude in text_lower for exclude in exclude_keywords_lower
            ):
                rejected[msg["id"]] = "rejected_by_exclude_keywords"
                continue

            # Проверяем включающие слова
            if keywords_lower and not any(keyword in text_lower for keyword in keywords_lower):
                rejected[msg["id"]] = "rejected_by_keywords_mismatch"
                continue

            filtered.append(msg)

        return filtered, rejected

    async def filter_duplicates(self, messages: list[dict]) -> tuple[list[dict], dict[int, str]]:
        """
        Фильтрация дубликатов через embeddings

        Оптимизировано (CR-H1): загружаем published_embeddings один раз и кэшируем
        Оптимизировано (CR-C5): используем batch encoding вместо последовательного encode
        Улучшено: двухэтапная дедупликация (published + intra-batch)

        Returns:
            Tuple of (unique_messages, rejected_reasons)
            where rejected_reasons maps message_id -> rejection_reason
        """
        unique = []
        rejected = {}

        if not messages:
            return unique, rejected

        # CR-H1: Загружаем published embeddings один раз и кэшируем
        # FIX-DUPLICATE-1: Проверяем TTL кэша и перезагружаем если устарел
        # Sprint 6.3: Неблокирующий доступ к БД
        cache_needs_reload = False
        if self._cached_published_embeddings is None:
            cache_needs_reload = True
            logger.debug("Кэш embeddings пуст, требуется загрузка")
        elif self._cache_timestamp is None:
            cache_needs_reload = True
            logger.debug("Timestamp кэша отсутствует, требуется перезагрузка")
        else:
            # Проверяем возраст кэша
            cache_age_seconds = (datetime.now() - self._cache_timestamp).total_seconds()
            if cache_age_seconds > self._cache_ttl_seconds:
                cache_needs_reload = True
                logger.info(
                    f"Кэш embeddings устарел (возраст: {cache_age_seconds:.1f}с, TTL: {self._cache_ttl_seconds}с), "
                    f"выполняется перезагрузка из БД"
                )

        if cache_needs_reload:
            # FIX-DUPLICATE-6: Используем конфигурируемое временное окно вместо хардкода 60
            self._cached_published_embeddings = await asyncio.to_thread(
                self.db.get_published_embeddings, days=self.duplicate_time_window_days
            )
            self._cache_timestamp = datetime.now()
            # Сбрасываем матрицу embeddings при перезагрузке кэша
            self._published_embeddings_matrix = None
            self._published_embeddings_ids = None
            logger.info(
                f"Загружено {len(self._cached_published_embeddings)} published embeddings в кэш "
                f"(TTL: {self._cache_ttl_seconds}с)"
            )

        # QA-4: Строим матрицу embeddings один раз для всех проверок
        # Sprint 6.3.4: используем кэш напрямую, без промежуточной переменной
        if self._published_embeddings_matrix is None and self._cached_published_embeddings:
            self._published_embeddings_ids = [post_id for post_id, _ in self._cached_published_embeddings]
            self._published_embeddings_matrix = np.array([emb for _, emb in self._cached_published_embeddings])
            logger.debug(
                f"QA-4: Построена матрица embeddings {self._published_embeddings_matrix.shape} "
                f"для оптимизации дедупликации"
            )

        # CR-C5: Батчевое кодирование всех сообщений сразу (async, non-blocking)
        texts = [msg["text"] for msg in messages]
        embeddings_array = await self.embeddings.encode_batch_async(texts, batch_size=32)
        logger.debug(f"CR-C5: Batch encoded {len(texts)} messages (shape: {embeddings_array.shape})")

        # ЭТАП 1: Проверяем каждое сообщение на дубликаты с опубликованными
        unique_from_published = []
        unique_embeddings = []

        for msg, embedding in zip(messages, embeddings_array):
            # Проверяем на дубликаты (inline вместо db.check_duplicate)
            # Sprint 6.3.4: удалён неиспользуемый аргумент published_embeddings
            is_duplicate = self._check_duplicate_inline(
                embedding, self.duplicate_threshold
            )

            if is_duplicate:
                rejected[msg["id"]] = "is_duplicate"
                continue

            unique_from_published.append(msg)
            unique_embeddings.append(embedding)

        logger.debug(
            f"После проверки с published: {len(unique_from_published)} уникальных "
            f"({len(rejected)} дубликатов)"
        )

        # ЭТАП 2 (НОВОЕ): Проверяем дубликаты внутри батча новых сообщений
        # Это решает проблему когда одна новость попала в несколько каналов
        intra_batch_duplicates = 0
        seen_embeddings = []

        for msg, embedding in zip(unique_from_published, unique_embeddings):
            if not seen_embeddings:
                # Первое сообщение всегда уникально
                unique.append(msg)
                seen_embeddings.append(embedding)
                continue

            # Проверяем similarity с уже принятыми сообщениями из батча
            seen_matrix = np.array(seen_embeddings)
            similarities = self.embeddings.batch_cosine_similarity(embedding, seen_matrix)
            max_similarity = np.max(similarities) if len(similarities) > 0 else 0.0

            if max_similarity >= self.duplicate_threshold:
                # Найден дубликат внутри батча
                rejected[msg["id"]] = "intra_batch_duplicate"
                intra_batch_duplicates += 1
                logger.debug(
                    f"Intra-batch дубликат обнаружен: msg_id={msg['id']}, "
                    f"similarity={max_similarity:.3f}"
                )
            else:
                # Уникальное сообщение
                unique.append(msg)
                seen_embeddings.append(embedding)

        logger.info(
            f"Дедупликация завершена: {len(unique)} уникальных, "
            f"{len(rejected)} дубликатов (из них {intra_batch_duplicates} внутри батча)"
        )

        return unique, rejected

    async def deduplicate_selected_posts(
        self, posts: list[dict], threshold: float = 0.78
    ) -> tuple[list[dict], list[dict]]:
        """
        Дедупликация отобранных Gemini новостей перед модерацией

        Двухэтапная дедупликация:
        1. Точная дедупликация по source_message_id (один raw_message не может быть выбран дважды)
        2. Семантическая дедупликация по embeddings (похожие новости из разных источников)

        Args:
            posts: Список новостей после отбора Gemini (с title, description)
            threshold: Порог схожести (FIX-DUPLICATE-2: снижен с 0.85 до 0.78 для детекции перефразированных дубликатов)

        Returns:
            Tuple of (unique_posts, duplicates)
        """
        if not posts:
            return [], []

        duplicates = []

        # ЭТАП 1: Точная дедупликация по source_message_id
        # Gemini может вернуть одно сообщение несколько раз (из разных чанков или категорий)
        seen_source_ids: set[int] = set()
        unique_by_id = []
        id_duplicates = 0

        for post in posts:
            source_id = post.get("source_message_id")
            if source_id is not None and source_id in seen_source_ids:
                duplicates.append(post)
                id_duplicates += 1
                logger.debug(
                    f"🔍 Дубликат по source_message_id={source_id}: '{post.get('title', '')[:40]}...'"
                )
                continue
            if source_id is not None:
                seen_source_ids.add(source_id)
            unique_by_id.append(post)

        if id_duplicates > 0:
            logger.info(f"🔍 Удалено {id_duplicates} дубликатов по source_message_id")

        # ЭТАП 2: Семантическая дедупликация по embeddings
        # Создаём embeddings для каждого поста
        # Используем оригинальный text для точной дедупликации (LLM-генерированные title/description могут отличаться)
        texts = [
            post.get('text', f"{post.get('title', '')} {post.get('description', '')}")
            for post in unique_by_id
        ]
        embeddings_array = await self.embeddings.encode_batch_async(texts, batch_size=32)

        # FIX-DUPLICATE-4: Используем DBSCAN или fixed threshold в зависимости от конфигурации
        if self.use_dbscan:
            logger.debug(
                f"Post-Gemini DBSCAN дедупликация: проверяем {len(unique_by_id)} новостей "
                f"(eps={self.dbscan_eps}, min_samples={self.dbscan_min_samples})"
            )
            unique, semantic_dups = self._deduplicate_with_dbscan(unique_by_id, embeddings_array)
        else:
            logger.debug(
                f"Post-Gemini threshold дедупликация: проверяем {len(unique_by_id)} новостей (порог={threshold})"
            )
            unique, semantic_dups = self._deduplicate_with_threshold(unique_by_id, embeddings_array, threshold)

        duplicates.extend(semantic_dups)
        semantic_duplicates = len(semantic_dups)

        logger.info(
            f"✅ Post-Gemini дедупликация: {len(unique)} уникальных, "
            f"{len(duplicates)} дубликатов удалено ({id_duplicates} по ID, {semantic_duplicates} семантических)"
        )

        return unique, duplicates

    def _deduplicate_with_dbscan(
        self, posts: list[dict], embeddings_array: np.ndarray
    ) -> tuple[list[dict], list[dict]]:
        """
        FIX-DUPLICATE-4: DBSCAN-based дедупликация

        Использует DBSCAN (Density-Based Spatial Clustering) для поиска кластеров
        похожих новостей. Из каждого кластера оставляет только один представитель.

        Преимущества над fixed threshold:
        - Автоматически находит кластеры похожих новостей
        - Учитывает локальную плотность (5 похожих новостей = 1 кластер)
        - Outliers (уникальные новости) остаются уникальными

        Args:
            posts: Список новостей
            embeddings_array: Numpy array с embeddings (shape: [n_posts, embedding_dim])

        Returns:
            Tuple of (unique_posts, duplicates)
        """
        if len(posts) == 0:
            return [], []

        if len(posts) == 1:
            # Один пост всегда уникален
            return posts, []

        try:
            from sklearn.cluster import DBSCAN
        except ImportError:
            logger.warning(
                "sklearn не установлен, используется fallback на fixed threshold дедупликацию. "
                "Установите: pip install scikit-learn"
            )
            # Fallback на стандартный метод
            return self._deduplicate_with_threshold(posts, embeddings_array, self.duplicate_threshold)

        # Запускаем DBSCAN
        dbscan = DBSCAN(
            eps=self.dbscan_eps,
            min_samples=self.dbscan_min_samples,
            metric="cosine",
        )
        labels = dbscan.fit_predict(embeddings_array)

        logger.debug(
            f"DBSCAN дедупликация: найдено {len(set(labels))} кластеров "
            f"(eps={self.dbscan_eps}, min_samples={self.dbscan_min_samples})"
        )

        # Группируем посты по кластерам
        unique = []
        duplicates = []
        cluster_representatives: dict[int, int] = {}  # cluster_id -> index of representative

        for idx, (post, label) in enumerate(zip(posts, labels)):
            if label == -1:
                # Outlier (шум) - считаем уникальным
                unique.append(post)
                logger.debug(f"DBSCAN: outlier #{idx} '{post.get('title', '')[:40]}...' - уникальный")
            else:
                # Элемент кластера
                if label not in cluster_representatives:
                    # Первый элемент кластера - представитель
                    cluster_representatives[label] = idx
                    unique.append(post)
                    logger.debug(
                        f"DBSCAN: кластер {label}, представитель #{idx} '{post.get('title', '')[:40]}...'"
                    )
                else:
                    # Дубликат - не первый в кластере
                    duplicates.append(post)
                    representative_idx = cluster_representatives[label]
                    logger.info(
                        f"🔍 DBSCAN дубликат: '{post.get('title', '')[:50]}...' "
                        f"в кластере {label} (представитель #{representative_idx})"
                    )

        logger.info(
            f"✅ DBSCAN дедупликация: {len(unique)} уникальных, "
            f"{len(duplicates)} дубликатов удалено"
        )

        return unique, duplicates

    def _deduplicate_with_threshold(
        self, posts: list[dict], embeddings_array: np.ndarray, threshold: float
    ) -> tuple[list[dict], list[dict]]:
        """
        Стандартная дедупликация с fixed threshold (используется как fallback)

        Args:
            posts: Список новостей
            embeddings_array: Numpy array с embeddings
            threshold: Порог схожести

        Returns:
            Tuple of (unique_posts, duplicates)
        """
        unique = []
        duplicates = []
        seen_embeddings = []

        for post, embedding in zip(posts, embeddings_array):
            if not seen_embeddings:
                unique.append(post)
                seen_embeddings.append(embedding)
                continue

            # Проверяем similarity с уже принятыми постами
            seen_matrix = np.array(seen_embeddings)
            similarities = self.embeddings.batch_cosine_similarity(embedding, seen_matrix)
            max_similarity = np.max(similarities) if len(similarities) > 0 else 0.0

            if max_similarity >= threshold:
                duplicates.append(post)
                duplicate_idx = np.argmax(similarities)
                logger.info(
                    f"🔍 Threshold дубликат: '{post.get('title', '')[:50]}...' "
                    f"похожа на #{duplicate_idx+1} (similarity={max_similarity:.3f})"
                )
            else:
                unique.append(post)
                seen_embeddings.append(embedding)

        return unique, duplicates

    def _update_published_cache(self, post_ids: list[int], embeddings: list[np.ndarray]):
        """
        QA-2: Обновить кэш published embeddings после публикации
        QA-4: Также обновляем матрицу embeddings для оптимизации дедупликации
        FIX-DUPLICATE-1: Обновляем timestamp кэша при инкрементальном обновлении

        Инкрементально добавляет новые embeddings в кэш, чтобы последующие
        категории в том же запуске могли детектировать дубликаты.

        Args:
            post_ids: Список source_message_id опубликованных постов
            embeddings: Соответствующие embeddings
        """
        if self._cached_published_embeddings is None:
            # Кэш ещё не инициализирован - инициализируем
            self._cached_published_embeddings = []
            self._cache_timestamp = datetime.now()
            logger.debug("QA-2: Инициализирован кэш published embeddings")

        # Добавляем новые embeddings в кэш
        new_entries = list(zip(post_ids, embeddings))
        self._cached_published_embeddings.extend(new_entries)

        # FIX-DUPLICATE-1: Обновляем timestamp при инкрементальном обновлении
        # Это гарантирует что кэш считается свежим после добавления новых embeddings
        self._cache_timestamp = datetime.now()

        # QA-4: Обновляем матрицу embeddings инкрементально
        if self._published_embeddings_matrix is not None and len(embeddings) > 0:
            # Добавляем новые векторы к существующей матрице
            new_matrix = np.array(embeddings)
            self._published_embeddings_matrix = np.vstack([self._published_embeddings_matrix, new_matrix])
            self._published_embeddings_ids.extend(post_ids)

            logger.debug(
                f"QA-4: Обновлена матрица embeddings, новый размер: {self._published_embeddings_matrix.shape}"
            )

        logger.debug(
            f"QA-2: Добавлено {len(new_entries)} embeddings в кэш. "
            f"Всего в кэше: {len(self._cached_published_embeddings)}"
        )

    def _check_duplicate_inline(
        self, embedding: np.ndarray, threshold: float = 0.78
    ) -> bool:
        """
        Проверить дубликат inline без обращения к БД (оптимизация CR-H1)
        Оптимизировано (CR-C5): используем batch_cosine_similarity для векторизации
        Оптимизировано (QA-4): переиспользуем кэшированную матрицу вместо пересоздания
        Рефакторинг (Sprint 6.3.4): удалён неиспользуемый параметр published_embeddings
        FIX-DUPLICATE-2: Снижен порог с 0.85 до 0.78

        Args:
            embedding: Embedding для проверки
            threshold: Порог схожести

        Returns:
            True если найден дубликат
        """
        # QA-4: Используем кэшированную матрицу вместо пересоздания каждый раз
        if self._published_embeddings_matrix is None or len(self._published_embeddings_matrix) == 0:
            return False

        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm == 0:
            logger.warning("Получен embedding с нулевой нормой при проверке дубликатов")
            return False

        # QA-4: Используем готовую матрицу (переиспользуем для всех проверок)
        # Вычисляем все similarity scores за один раз
        similarities = self.embeddings.batch_cosine_similarity(embedding, self._published_embeddings_matrix)

        # Находим максимальную схожесть
        if len(similarities) > 0:
            max_similarity = np.max(similarities)
            if max_similarity >= threshold:
                # QA-4: Находим post_id из кэшированного списка IDs
                max_idx = np.argmax(similarities)
                post_id = self._published_embeddings_ids[max_idx]
                logger.debug(
                    f"Найден дубликат: post_id={post_id}, similarity={max_similarity:.3f}"
                )
                return True

        return False

    async def moderate_posts(
        self, client: TelegramClient, posts: list[dict], marketplace: str
    ) -> list[dict]:
        """Отправка новостей на модерацию через Telegram"""

        logger.info(f"📋 Отправка {len(posts)} новостей на модерацию ({marketplace})")

        # Присваиваем ID для модерации
        for idx, post in enumerate(posts, 1):
            post["moderation_id"] = idx

        # Формируем сообщение для модерации
        message = self._format_moderation_message(posts, marketplace)

        # Отправляем в личку (используем my_personal_account из конфига)
        personal_account = self.config.my_personal_account
        await client.send_message(personal_account, message)

        logger.info(f"✅ Сообщение для модерации отправлено в {personal_account}")

        # TODO: Здесь можно добавить логику ожидания ответа от модератора
        # Пока возвращаем все посты (автоутверждение)
        return posts

    async def process_all_categories(self, client: TelegramClient):
        """Обработка всех новостей с 3-категорийной системой (5 WB + 5 Ozon + 5 Общих = 15)"""

        logger.info("=" * 80)
        logger.info("📦 ОБРАБОТКА НОВОСТЕЙ: ВСЕ КАТЕГОРИИ (3-КАТЕГОРИЙНАЯ СИСТЕМА)")
        logger.info("=" * 80)

        # Sprint 6.3: Неблокирующий доступ к БД
        base_messages = await asyncio.to_thread(self.db.get_unprocessed_messages, hours=24)
        logger.info(f"Загружено {len(base_messages)} необработанных сообщений")

        if not base_messages:
            logger.info("Нет новых сообщений")
            return

        # Словарь для отслеживания причин отклонения
        all_rejected = {}

        # ШАГ 2: Фильтруем по глобальным исключающим словам
        filtered_messages = []
        for msg in base_messages:
            text_lower = msg["text"].lower()
            if self.all_exclude_keywords_lower and any(
                exclude in text_lower for exclude in self.all_exclude_keywords_lower
            ):
                all_rejected[msg["id"]] = "rejected_by_exclude_keywords"
                continue
            filtered_messages.append(msg)

        logger.info(f"После фильтрации исключений: {len(filtered_messages)} сообщений")

        if not filtered_messages:
            # Помечаем отфильтрованные как processed
            # Sprint 6.4: Батч-обработка вместо N вызовов
            updates = [
                {'message_id': msg_id, 'rejection_reason': reason}
                for msg_id, reason in all_rejected.items()
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            logger.info("Нет сообщений после фильтрации исключений")
            return

        # ШАГ 3: Проверка дубликатов
        unique_messages, rejected_duplicates = await self.filter_duplicates(filtered_messages)
        all_rejected.update(rejected_duplicates)
        logger.info(f"После проверки дубликатов: {len(unique_messages)} уникальных")

        if not unique_messages:
            # Помечаем все отфильтрованные как processed
            # Sprint 6.4: Батч-обработка вместо N вызовов
            updates = [
                {
                    'message_id': msg_id,
                    'is_duplicate': (reason == "is_duplicate"),
                    'rejection_reason': reason
                }
                for msg_id, reason in all_rejected.items()
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            logger.warning("Все сообщения являются дубликатами")
            return

        # ШАГ 4: Тематическая память — получаем недавно опубликованные темы
        recently_published_raw = await asyncio.to_thread(
            self.db.get_recently_published_texts, 7, 30
        )
        topic_summaries = [item["text"] for item in recently_published_raw] if recently_published_raw else None
        if topic_summaries:
            logger.info(f"Тематическая память: {len(topic_summaries)} недавних тем загружено")

        # ШАГ 5: Отбор по категориям через LLM (Claude/Gemini по конфигу)
        # Поддерживает любые категории из конфига, не только marketplace-специфичные
        categories = await asyncio.to_thread(
            self.llm_client.select_by_categories,
            unique_messages,
            category_counts=self.all_digest_counts,
            recently_published=topic_summaries,
            category_descriptions=self.all_digest_descriptions,
        )

        # Подсчитываем сколько получилось (динамически для всех категорий)
        category_stats = {cat: len(posts) for cat, posts in categories.items()}
        total_count = sum(category_stats.values())

        # Формируем красивый лог с категориями
        stats_str = ", ".join(f"{cat}={count}" for cat, count in category_stats.items())
        logger.info(f"LLM отобрал: {stats_str}, Всего={total_count}")

        selected_ids = {
            post["source_message_id"]
            for posts in categories.values()
            for post in posts
            if post.get("source_message_id")
        }

        if total_count == 0:
            logger.warning("Gemini не отобрал ни одной новости")
            # Sprint 6.4: Батч-обработка вместо N вызовов
            updates = [
                {'message_id': msg["id"], 'rejection_reason': "rejected_by_llm"}
                for msg in unique_messages
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            return

        # ШАГ 4.5 (НОВОЕ): Дедупликация после Gemini
        # Gemini может выбрать похожие новости из разных чунков обработки
        # Фильтруем почти идентичные новости перед отправкой на модерацию
        # FIX-DUPLICATE-2: Используем конфигурируемый порог вместо хардкода
        all_selected_posts = [post for posts in categories.values() for post in posts]
        unique_posts, post_duplicates = await self.deduplicate_selected_posts(
            all_selected_posts, threshold=self.duplicate_threshold
        )

        # Если после дедупликации не осталось новостей
        if not unique_posts:
            logger.warning("После post-Gemini дедупликации не осталось новостей")
            updates = [
                {'message_id': msg["id"], 'rejection_reason': "rejected_by_llm"}
                for msg in unique_messages
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            return

        # Пересобираем categories без дубликатов
        # Сохраняем только уникальные посты в каждой категории
        unique_post_ids = {id(post) for post in unique_posts}
        filtered_categories = {}
        for cat_name, posts in categories.items():
            filtered_posts = [post for post in posts if id(post) in unique_post_ids]
            if filtered_posts:
                filtered_categories[cat_name] = filtered_posts

        categories = filtered_categories
        total_count = len(unique_posts)

        # Обновляем selected_ids без дубликатов
        selected_ids = {
            post["source_message_id"]
            for post in unique_posts
            if post.get("source_message_id")
        }

        logger.info(
            f"После post-Gemini дедупликации: {total_count} уникальных новостей "
            f"({len(post_duplicates)} дубликатов удалено)"
        )

        # ШАГ 5: Автоматическая модерация (финальная дедупликация + топ-N)
        # Собираем все посты из категорий в единый список
        all_posts = [post for posts in categories.values() for post in posts]

        if self.auto_moderation:
            # АВТОМАТИЧЕСКИЙ РЕЖИМ: без участия человека
            logger.info("🤖 Автоматическая модерация включена")
            moderation_result: ModerationResult = await self.auto_moderator.moderate(
                all_posts,
                top_n=self.final_top_n,  # Ограничиваем финальное количество (по умолчанию 10)
            )
            approved_posts = moderation_result.approved_posts

            if not approved_posts:
                logger.warning("Все новости отклонены автомодератором")
                updates = [
                    {'message_id': msg_id, 'rejection_reason': "rejected_by_auto_moderator"}
                    for msg_id in selected_ids
                ]
                await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
                return

            # Обновляем причины отклонения из результата модерации
            auto_rejection_reasons = moderation_result.rejection_reasons

        elif self.moderation_enabled:
            # РУЧНОЙ РЕЖИМ: с подтверждением от модератора (legacy)
            logger.info("👤 Ручная модерация включена")
            approved_posts = await self.moderate_categories(client, categories)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                updates = [
                    {'message_id': msg_id, 'rejection_reason': "rejected_by_moderator"}
                    for msg_id in selected_ids
                ]
                await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
                return
            auto_rejection_reasons = {}
        else:
            # БЕЗ МОДЕРАЦИИ: берем все что есть
            approved_posts = all_posts
            auto_rejection_reasons = {}

        approved_ids = {
            post.get("source_message_id")
            for post in approved_posts
            if post.get("source_message_id")
        }

        # Сохраняем ID для последующей пометки (только после успешной публикации)
        rejected_after_moderation = selected_ids - approved_ids
        unique_ids = {msg["id"] for msg in unique_messages}
        not_selected_ids = unique_ids - selected_ids

        # ШАГ 6: Публикация
        target_channel = (
            self.all_digest_channel
            if self.all_digest_enabled and self.all_digest_channel
            else next(
                (mp.target_channel for mp in self.categories.values() if mp.target_channel),
                None,
            )
        )

        if self.auto_moderation:
            # АВТОМАТИЧЕСКИЙ РЕЖИМ: сразу публикуем
            logger.info(f"📢 Автопубликация {len(approved_posts)} новостей в {target_channel}...")

            await self.publish_digest(
                client,
                approved_posts,
                "категории",
                target_channel,
                display_name="Категории",
            )
        else:
            # РУЧНОЙ РЕЖИМ: формируем дайджест и ждём утверждения
            digest_text = self._format_digest(approved_posts, target_channel)
            moderator_username = self.config.my_personal_account

            is_approved = await self._approve_digest(client, moderator_username, digest_text)

            if not is_approved:
                logger.warning("❌ Модератор отменил публикацию дайджеста")
                return

            logger.info("📢 Публикация утвержденного дайджеста...")

            await self.publish_digest(
                client,
                approved_posts,
                "категории",
                target_channel,
                display_name="Категории",
            )

        # ШАГ 7: Помечаем сообщения как обработанные (только после успешной публикации)

        # 7.1: Сообщения, которые вошли в публикацию
        await self._mark_messages_processed(approved_posts)

        # 7.2: Сообщения, которые прошли отбор Gemini, но были исключены модератором
        updates = []
        for msg_id in rejected_after_moderation:
            reason = auto_rejection_reasons.get(msg_id, "rejected_by_moderator")
            updates.append({'message_id': msg_id, 'rejection_reason': reason})
        if updates:
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # 7.3: Сообщения, которые Gemini не выбрал
        updates = [
            {'message_id': msg_id, 'rejection_reason': "rejected_by_llm"}
            for msg_id in not_selected_ids
        ]
        if updates:
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # 7.4: Сообщения, отфильтрованные по ключевым словам или дубликаты
        updates = [
            {
                'message_id': msg_id,
                'is_duplicate': (reason == "is_duplicate"),
                'rejection_reason': reason
            }
            for msg_id, reason in all_rejected.items()
        ]
        if updates:
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        logger.info("✅ Обработка всех категорий завершена!")

    async def _wait_for_moderation_response_retry(
        self, conv, total_posts: int, max_retries: int = 5
    ) -> list[int] | None:
        """
        Повторное ожидание ответа модератора (после некорректного ввода)

        Args:
            conv: Conversation объект
            total_posts: Общее количество новостей
            max_retries: Максимальное количество попыток

        Returns:
            Список номеров для исключения или None если отмена
        """
        for attempt in range(max_retries):
            try:
                response = await conv.get_response(timeout=float('inf'))
                response_text = response.message.strip().lower()

                logger.info(f"📨 Получен повторный ответ модератора: {response_text}")

                # Обработка команды отмены
                if response_text in ["отмена", "cancel"]:
                    await conv.send_message("❌ Модерация отменена")
                    return None

                # Обработка команды "опубликовать все"
                if response_text in ["0", "все", "all"]:
                    await conv.send_message(f"✅ Все {total_posts} новостей будут опубликованы")
                    return []

                # Парсинг номеров
                excluded_ids = []
                parts = response_text.split()

                for part in parts:
                    part = part.strip(",.")
                    if part.isdigit():
                        num = int(part)
                        if 1 <= num <= total_posts:
                            excluded_ids.append(num)
                        else:
                            logger.warning(f"Номер {num} вне диапазона 1-{total_posts}")

                if not excluded_ids:
                    remaining = max_retries - attempt - 1
                    if remaining > 0:
                        await conv.send_message(
                            f"⚠️ Не удалось распознать номера. "
                            f"Отправь номера через пробел (например: 1 2 3 5 6). "
                            f"Осталось попыток: {remaining}"
                        )
                        continue
                    else:
                        await conv.send_message(
                            "❌ Превышено количество попыток. Модерация отменена."
                        )
                        return None

                await conv.send_message(
                    f"✅ Исключено {len(excluded_ids)} новостей: {', '.join(map(str, excluded_ids))}\n"
                    f"Будет опубликовано: {total_posts - len(excluded_ids)} новостей"
                )
                return excluded_ids

            except Exception as e:
                logger.error(f"Ошибка при повторном ожидании ответа: {e}", exc_info=True)
                return None

        return None

    async def _wait_for_moderation_response(
        self, client: TelegramClient, personal_account: str, message: str, total_posts: int
    ) -> list[int] | None:
        """
        Ожидание ответа модератора через polling

        Args:
            client: Telegram клиент
            personal_account: Username модератора
            message: Сообщение для модерации
            total_posts: Общее количество новостей

        Returns:
            Список номеров для исключения или None если отмена
        """
        from datetime import datetime, timedelta, timezone

        logger.info("⏳ Отправка на модерацию и ожидание ответа...")

        try:
            # Отправляем сообщение модерации
            sent_message = await client.send_message(personal_account, message)
            sent_time = datetime.now(timezone.utc)
            logger.info(f"✅ Сообщение отправлено модератору {personal_account}")

            # Ждем ответа с таймаутом (в секундах)
            timeout_seconds = self.moderation_timeout_hours * 3600
            logger.info(f"⏰ Ожидание ответа модератора (timeout: {self.moderation_timeout_hours}ч)")

            check_interval = 3  # Проверяем каждые 3 секунды
            elapsed = 0

            while elapsed < timeout_seconds:
                await asyncio.sleep(check_interval)
                elapsed += check_interval

                # Получаем последние сообщения от модератора
                messages = await client.get_messages(personal_account, limit=10)

                # Ищем первое сообщение после отправки запроса
                for msg in messages:
                    if msg.date > sent_time and msg.out == False:  # Входящее сообщение после нашего
                        response_text = msg.text.strip().lower() if msg.text else ""

                        if not response_text:
                            continue

                        logger.info(f"📨 Получен ответ модератора: {response_text}")

                        # Обработка команды отмены
                        if response_text in ["отмена", "cancel"]:
                            await client.send_message(personal_account, "❌ Модерация отменена")
                            return None

                        # Обработка команды "опубликовать все"
                        if response_text in ["0", "все", "all"]:
                            await client.send_message(
                                personal_account,
                                f"✅ Все {total_posts} новостей будут опубликованы"
                            )
                            return []

                        # Парсинг номеров
                        excluded_ids = []
                        parts = response_text.split()

                        for part in parts:
                            # Удаляем возможные символы типа запятых
                            part = part.strip(",.")
                            if part.isdigit():
                                num = int(part)
                                if 1 <= num <= total_posts:
                                    excluded_ids.append(num)
                                else:
                                    logger.warning(f"Номер {num} вне диапазона 1-{total_posts}")

                        if not excluded_ids:
                            await client.send_message(
                                personal_account,
                                "⚠️ Не удалось распознать номера. "
                                "Отправь номера через пробел (например: 1 2 3 5 6)"
                            )
                            continue  # Продолжаем ждать

                        await client.send_message(
                            personal_account,
                            f"✅ Исключено {len(excluded_ids)} новостей: {', '.join(map(str, excluded_ids))}\n"
                            f"Будет опубликовано: {total_posts - len(excluded_ids)} новостей"
                        )
                        return excluded_ids

            # Timeout модерации - автоматически публикуем все новости
            logger.warning(
                f"⏰ Timeout модерации ({self.moderation_timeout_hours}ч) - "
                f"автоматическая публикация всех {total_posts} новостей"
            )
            try:
                await client.send_message(
                    personal_account,
                    f"⏰ Время модерации истекло ({self.moderation_timeout_hours}ч)\n"
                    f"✅ Все {total_posts} новостей будут опубликованы автоматически"
                )
            except Exception:
                pass  # Игнорируем ошибки отправки уведомления
            return []  # Пустой список = опубликовать все

        except Exception as e:
            logger.error(f"Ошибка при ожидании ответа модератора: {e}", exc_info=True)
            return None

    def _format_digest(self, approved_posts: list[dict], target_channel: str) -> str:
        """
        Форматирование финального дайджеста для публикации

        Args:
            approved_posts: Список одобренных новостей
            target_channel: Канал для публикации

        Returns:
            Отформатированный текст дайджеста
        """
        from datetime import timedelta
        from utils.timezone import now_msk

        yesterday = now_msk() - timedelta(days=1)
        date_str = yesterday.strftime("%d-%m-%Y")
        header = self.publication_header_template.format(
            date=date_str,
            display_name="Категории",
            marketplace="категории",
            channel=target_channel,
            profile=getattr(self.config, "profile", "")
        )

        digest_parts = [header, ""]

        for idx, post in enumerate(approved_posts, 1):
            title = post.get("title", "Без заголовка")
            description = post.get("description", "")
            source_link = post.get("source_link", "")

            digest_parts.append(f"{idx}. **{title}**")
            digest_parts.append(f"{description}")
            if source_link:
                digest_parts.append(source_link)
            digest_parts.append("")

        digest_parts.append(self.publication_footer_template)
        digest_text = "\n".join(digest_parts)

        return digest_text

    async def _approve_digest(
        self, client: TelegramClient, personal_account: str, digest_text: str
    ) -> bool:
        """
        Вторая стадия модерации: утверждение дайджеста перед публикацией

        Args:
            client: Telegram клиент
            personal_account: Username модератора
            digest_text: Отформатированный текст дайджеста (используется для подсчета длины)

        Returns:
            True если одобрено, False если отменено
        """
        from datetime import datetime, timedelta, timezone

        logger.info("📋 Отправка дайджеста на утверждение...")

        try:
            # Служебные части сообщения
            header = (
                "**📢 УТВЕРЖДЕНИЕ ДАЙДЖЕСТА**\n\n"
                f"📊 Готов дайджест из новостей\n"
                f"📏 Размер: {len(digest_text)} символов\n\n"
                + "=" * 50 + "\n\n"
            )

            footer = (
                "\n\n" + "=" * 50 + "\n\n"
                "Отправь команду для публикации:\n"
                "• `опубликовать` / `ok` / `да` - опубликовать\n"
                "• `отмена` - отменить публикацию\n"
            )

            # Вычисляем сколько символов доступно для preview дайджеста
            available_length = (
                self.TELEGRAM_MESSAGE_LIMIT - len(header) - len(footer) - self.PREVIEW_SAFETY_MARGIN
            )

            # Формируем preview дайджеста
            if len(digest_text) <= available_length:
                digest_preview = digest_text
            else:
                digest_preview = digest_text[:available_length] + "\n\n... (обрезано для превью)"

            # Собираем финальное сообщение
            approval_message = header + digest_preview + footer

            # Отправляем дайджест на утверждение
            sent_message = await client.send_message(personal_account, approval_message)
            sent_time = datetime.now(timezone.utc)
            logger.info(f"✅ Дайджест отправлен на утверждение модератору {personal_account}")

            # Ждем ответа с таймаутом 1 час
            timeout_seconds = 3600  # 1 час
            logger.info(f"⏰ Ожидание утверждения дайджеста (timeout: 1ч)")

            check_interval = 3  # Проверяем каждые 3 секунды
            elapsed = 0

            while elapsed < timeout_seconds:
                await asyncio.sleep(check_interval)
                elapsed += check_interval

                # Получаем последние сообщения от модератора
                messages = await client.get_messages(personal_account, limit=10)

                # Ищем первое сообщение после отправки запроса
                for msg in messages:
                    if msg.date > sent_time and msg.out == False:  # Входящее сообщение
                        response_text = msg.text.strip().lower() if msg.text else ""

                        if not response_text:
                            continue

                        logger.info(f"📨 Получен ответ модератора: {response_text}")

                        # Команда отмены
                        if response_text in ["отмена", "cancel"]:
                            await client.send_message(personal_account, "❌ Публикация дайджеста отменена")
                            logger.info("❌ Модератор отменил публикацию")
                            return False

                        # Команды утверждения
                        if response_text in ["опубликовать", "ok", "да", "yes"]:
                            await client.send_message(personal_account, "✅ Дайджест утвержден, публикуем...")
                            logger.info("✅ Модератор утвердил публикацию")
                            return True

                        # Неизвестная команда
                        await client.send_message(
                            personal_account,
                            "⚠️ Неизвестная команда. Используй:\n"
                            "• `опубликовать` / `ok` / `да` - опубликовать\n"
                            "• `отмена` - отменить"
                        )
                        continue

            # Timeout - автоматически утверждаем
            logger.warning("⏰ Timeout утверждения (1ч) - автоматическая публикация")
            try:
                await client.send_message(
                    personal_account,
                    "⏰ Время утверждения истекло (1ч)\n"
                    "✅ Дайджест будет опубликован автоматически"
                )
            except Exception:
                pass
            return True  # Автоматически утверждаем при timeout

        except Exception as e:
            logger.error(f"Ошибка при утверждении дайджеста: {e}", exc_info=True)
            return False

    async def _mark_messages_processed(self, approved_posts: list[dict]) -> None:
        """
        Помечает сообщения из одобренных новостей как обработанные в БД

        Args:
            approved_posts: Список одобренных постов с source_message_id
        """
        try:
            # Формируем батч-апдейты для БД
            updates = [
                {
                    'message_id': post.get("source_message_id"),
                    'gemini_score': post.get("score")
                }
                for post in approved_posts
                if post.get("source_message_id")
            ]

            if updates:
                await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
                logger.info(f"✅ Помечено {len(updates)} сообщений как обработанные")
            else:
                logger.warning("⚠️ Нет сообщений для пометки как обработанные")

        except Exception as e:
            logger.error(f"Ошибка при пометке сообщений как обработанные: {e}", exc_info=True)

    async def moderate_categories(
        self, client: TelegramClient, categories: dict[str, list[dict]]
    ) -> list[dict]:
        """Интерактивная модерация: исключение 5 из 15 новостей (по категориям)"""

        # Объединяем все новости из 3 категорий
        all_posts = []

        # Добавляем категорию к каждому посту
        for cat_name, posts in categories.items():
            for post in posts:
                post["category"] = cat_name
                all_posts.append(post)

        # ВАЖНО: Сортируем по score ПЕРЕД присвоением moderation_id
        # чтобы номера совпадали с тем, что видит пользователь в сообщении модерации
        all_posts.sort(key=lambda x: x.get('score', 0), reverse=True)

        total = len(all_posts)
        exclude_goal = max(0, min(self.processor_exclude_count, total))
        logger.info(
            "📋 Отправка %s новостей на модерацию (нужно исключить %s)",
            total,
            exclude_goal,
        )

        # Присваиваем ID для модерации ПОСЛЕ сортировки
        for idx, post in enumerate(all_posts, 1):
            post["moderation_id"] = idx

        # Формируем сообщение для модерации (передаем УЖЕ отсортированный список)
        message = self._format_categories_moderation_message(all_posts, exclude_goal)

        # Отправляем в личку и ждем ответа
        personal_account = self.config.my_personal_account
        excluded_ids = await self._wait_for_moderation_response(
            client, personal_account, message, total
        )

        if excluded_ids is None:
            # Модератор отменил модерацию
            logger.warning("Модерация отменена модератором")
            return []

        # Фильтруем посты - исключаем выбранные номера
        approved_posts = [post for post in all_posts if post["moderation_id"] not in excluded_ids]

        logger.info(
            f"✅ Модерация завершена: исключено {len(excluded_ids)}, одобрено {len(approved_posts)}"
        )
        return approved_posts

    def _format_categories_moderation_message(
        self, all_posts: list[dict], exclude_goal: int
    ) -> str:
        """Форматирование сообщения для модерации 3-категорийной системы

        Args:
            all_posts: УЖЕ отсортированный список новостей с присвоенными moderation_id
            exclude_goal: Количество новостей для исключения
        """

        # Используем УЖЕ отсортированный список (не пересортировываем!)

        lines = ["📋 **МОДЕРАЦИЯ: ТОПОВЫЕ НОВОСТИ**"]
        if exclude_goal > 0:
            lines.append(
                f"_Нужно исключить {exclude_goal} новостей из {len(all_posts)}_\n"
            )
        else:
            lines.append("_При необходимости можно исключить новости, отправив их номера_\n")

        # Выводим все новости единым списком (УЖЕ отсортированы по score)
        for post in all_posts:
            mod_id = post.get('moderation_id', 0)
            emoji = NUMBER_EMOJIS.get(mod_id, f"{mod_id}.")
            category_tag = post.get('category', '').upper()
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10 | 📦 {category_tag}\n")

        lines.append("=" * 50)
        lines.append(f"📊 **Всего:** {len(all_posts)} новостей\n")
        lines.append("**Инструкция:**")
        if exclude_goal > 0:
            lines.append(
                f"Отправь номера которые **ИСКЛЮЧИТЬ из ПУБЛИКАЦИИ** через пробел ({exclude_goal} шт.)"
            )
            sample = " ".join(str(i) for i in range(1, min(exclude_goal, 5) + 1))
            lines.append(f"Например: `{sample}`\n")
        else:
            lines.append("При необходимости отправь номера, которые нужно исключить из публикации\n")
        lines.append("Или отправь `0` или `все` чтобы опубликовать все новости")
        lines.append("Или отправь `отмена` чтобы отменить модерацию")

        return "\n".join(lines)

    def _format_moderation_message(self, posts: list[dict], marketplace: str) -> str:
        """Форматирование сообщения для модерации"""
        lines = [f"📋 **МОДЕРАЦИЯ: {marketplace.upper()}**"]
        lines.append("_(Отсортировано по важности)_\n")

        for post in posts:
            idx = post["moderation_id"]
            emoji = NUMBER_EMOJIS.get(idx, f"{idx}️⃣")

            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:150]}..._")
            lines.append(f"⭐ Оценка: {post.get('score', 0)}/10\n")

        lines.append("=" * 50)
        lines.append(f"📊 **Всего новостей:** {len(posts)}\n")
        lines.append("**Инструкция:**")
        lines.append("Отправь номера для УДАЛЕНИЯ через пробел")
        lines.append("Например: `1 3 5` - удалит новости 1, 3 и 5\n")
        lines.append("Отправь `0` или `все` чтобы одобрить ВСЕ новости")

        return "\n".join(lines)

    @staticmethod
    @staticmethod
    def _split_text_by_limit(text: str, limit: int) -> list[str]:
        """
        Разбивает готовый текст дайджеста на части не длиннее limit символов.

        Алгоритм:
        - Режем по абзацам (двойной перенос строки) — не рвём новость посередине
        - Если один абзац сам по себе > limit — режем по строкам
        - Добавляет метку «часть N/M» в конец каждой части (кроме последней если одна)

        Returns:
            Список строк-сообщений, каждое <= limit символов.
        """
        SUFFIX_RESERVE = 20  # «\n\n📄 Часть 1/9» — запас под метку
        effective_limit = limit - SUFFIX_RESERVE

        # Разбиваем на абзацы (блоки между пустыми строками)
        paragraphs = text.split("\n\n")

        parts: list[str] = []
        current_chunks: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para) + 2  # +2 за \n\n

            # Абзац сам по себе слишком большой — режем по строкам
            if para_len > effective_limit:
                # Сначала сохраняем накопленное
                if current_chunks:
                    parts.append("\n\n".join(current_chunks))
                    current_chunks = []
                    current_len = 0
                # Режем абзац по строкам
                for line in para.split("\n"):
                    line_len = len(line) + 1
                    if current_len + line_len > effective_limit and current_chunks:
                        parts.append("\n\n".join(current_chunks))
                        current_chunks = [line]
                        current_len = line_len
                    else:
                        current_chunks.append(line)
                        current_len += line_len
                continue

            if current_len + para_len > effective_limit and current_chunks:
                # Не влезает — сохраняем и начинаем новую часть
                parts.append("\n\n".join(current_chunks))
                current_chunks = [para]
                current_len = para_len
            else:
                current_chunks.append(para)
                current_len += para_len

        if current_chunks:
            parts.append("\n\n".join(current_chunks))

        # Добавляем метку «часть N/M» если частей больше одной
        if len(parts) > 1:
            total = len(parts)
            parts = [f"{p}\n\n📄 Часть {i}/{total}" for i, p in enumerate(parts, 1)]

        return parts

    @staticmethod
    def _split_digest_by_limit(lines: list[str], limit: int) -> list[str]:
        """Устаревший метод — делегирует в _split_text_by_limit."""
        return NewsProcessor._split_text_by_limit("\n".join(lines), limit)

    @staticmethod
    def _ensure_post_fields(post: dict) -> dict:
        """QA-1: Fallback-форматирование для постов без title/description.

        Делегирует в utils.formatters.ensure_post_fields.
        """
        return ensure_post_fields(post)

    async def publish_digest(
        self,
        client: TelegramClient,
        posts: list[dict],
        marketplace: str,
        target_channel: str,
        display_name: str | None = None,
    ):
        """Публикация дайджеста в канал"""

        logger.info(f"📤 Публикация {len(posts)} новостей в {target_channel}")

        # Формируем дайджест
        yesterday = now_msk() - timedelta(days=1)
        date_str = yesterday.strftime("%d-%m-%Y")
        header_name = display_name or marketplace

        context = {
            "date": date_str,
            "display_name": header_name,
            "marketplace": marketplace,
            "channel": target_channel,
            "profile": getattr(self.config, "profile", ""),
        }

        try:
            header_line = self.publication_header_template.format(**context)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Не удалось подставить параметры в publication.header_template: %s", exc
            )
            header_line = f"📌 Главные новости {header_name} за {date_str}"

        # Вычисляем footer
        footer = self.publication_footer_template.strip()
        footer_text = ""
        if footer:
            try:
                footer_text = footer.format(**context)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Не удалось подставить параметры в publication.footer_template: %s", exc
                )
                footer_text = footer

        # Пробуем переписать дайджест через LLM (второй проход Claude)
        # Если LLM-дайджест не влезает — обрезаем посты и повторяем
        digest = ""
        active_posts = list(posts)

        while True:
            if not active_posts:
                digest = header_line.strip() + "\n\n" + footer_text
                logger.warning("⚠️ Все посты обрезаны — публикуем только заголовок")
                break

            try:
                rewritten = await asyncio.to_thread(
                    self.llm_client.rewrite_digest,
                    active_posts,
                    header_line.strip(),
                    footer_text,
                )
                if rewritten:
                    digest = rewritten
                    logger.info("✍️ Дайджест переписан через LLM (%d символов, %d новостей)",
                                len(digest), len(active_posts))
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM rewrite_digest не удался, используем шаблон: %s", exc)

            # Fallback: шаблонное форматирование
            if not digest:
                lines = [header_line.strip() + "\n"]
                for idx, post in enumerate(active_posts, 1):
                    post = self._ensure_post_fields(post)
                    emoji = NUMBER_EMOJIS.get(idx, f"{idx}" + "\ufe0f\u20e3")
                    lines.append(f"{emoji} **{post['title']}**\n")
                    lines.append(f"{post['description']}\n")
                    if post.get("source_link"):
                        lines.append(f"{post['source_link']}\n")
                if footer_text:
                    lines.append(footer_text)
                digest = "\n".join(lines)

            # Влезает — выходим
            if len(digest) <= self.TELEGRAM_MESSAGE_LIMIT:
                break

            # Не влезает — убираем последнюю новость и пробуем снова
            dropped = active_posts.pop()
            logger.warning(
                "⚠️ Дайджест %d симв > %d лимит. Убираем последнюю новость ('%s'), осталось %d.",
                len(digest), self.TELEGRAM_MESSAGE_LIMIT,
                dropped.get("title", "?")[:50], len(active_posts),
            )
            digest = ""  # сбрасываем для следующей итерации

        digest_parts = [digest]

        # Публикация дайджеста
        async def resolve_entity(channel: str, max_wait: int = 600):
            """Резолвит entity канала с обработкой FloodWait.
            Ждёт если FloodWait <= max_wait, иначе пробрасывает исключение."""
            while True:
                try:
                    return await client.get_entity(channel)
                except FloodWaitError as e:
                    if e.seconds > max_wait:
                        logger.error(
                            "❌ FloodWait %ds при резолве %s превышает лимит %ds — пропускаем",
                            e.seconds, channel, max_wait,
                        )
                        raise
                    logger.warning(
                        "⏳ FloodWait %ds при резолве %s — ждём...", e.seconds, channel
                    )
                    await asyncio.sleep(e.seconds + 1)

        preview_channel = (self.publication_preview_channel or "").strip()
        if preview_channel:
            try:
                # Security: Rate limiting для защиты от Telegram API ban
                # Получаем ID канала для per-chat limiting
                preview_entity = await resolve_entity(preview_channel)
                for part in digest_parts:
                    await self._rate_limiter.acquire(
                        chat_id=preview_entity.id,
                        endpoint="send_message",
                        priority=1  # Preview имеет средний приоритет
                    )
                    await client.send_message(preview_channel, part)
                logger.info("📄 Черновик дайджеста отправлен в %s", preview_channel)
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось отправить превью в %s: %s", preview_channel, exc)

        # Публикуем в основной канал
        target_entity = await resolve_entity(target_channel)
        for part in digest_parts:
            await self._rate_limiter.acquire(
                chat_id=target_entity.id,
                endpoint="send_message",
                priority=2  # Публикация имеет высокий приоритет
            )
            await client.send_message(target_channel, part)
        logger.info(f"✅ Дайджест опубликован в {target_channel}")

        notify_account = (self.publication_notify_account or "").strip()
        if notify_account:
            try:
                notify_entity = await resolve_entity(notify_account)
                await self._rate_limiter.acquire(
                    chat_id=notify_entity.id,
                    endpoint="send_message",
                    priority=0  # Уведомление имеет низкий приоритет
                )
                await client.send_message(
                    notify_account,
                    f"✅ Дайджест на {context['date']} опубликован в {target_channel}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось отправить уведомление %s: %s", notify_account, exc)

        # Сохраняем embeddings (CR-C5: batch encoding)
        texts = [post["text"] for post in posts]
        embeddings_array = await self.embeddings.encode_batch_async(texts, batch_size=32)
        logger.debug(f"CR-C5: Batch encoded {len(texts)} posts for saving")

        post_ids = []
        # Sprint 6.3: Неблокирующий доступ к БД
        for post, embedding in zip(posts, embeddings_array):
            try:
                await asyncio.to_thread(
                    self.db.save_published,
                    text=post["text"],
                    embedding=embedding,
                    source_message_id=post["source_message_id"],
                    source_channel_id=post["source_channel_id"],
                )
                post_ids.append(post["source_message_id"])
            except Exception as e:
                logger.error(
                    f"Ошибка сохранения поста {post.get('source_message_id')}: {e}",
                    exc_info=True,
                )

        logger.info(f"💾 Сохранено {len(posts)} embeddings в БД")

        # QA-2: Обновляем кэш после публикации для детектирования дубликатов в последующих категориях
        self._update_published_cache(post_ids, list(embeddings_array))

    async def run(self):
        """Запуск обработки новостей через 3-категорийную систему"""

        # Подключаемся к Telegram с использованием основной сессии
        # Используем safe_connect для предотвращения FloodWait блокировок
        session_name = self.config.get("telegram.session_name")
        client = TelegramClient(
            session_name, self.config.telegram_api_id, self.config.telegram_api_hash
        )

        await safe_connect(client, session_name)

        try:
            # Обрабатываем через 3-категорийную систему
            await self.process_all_categories(client)
        finally:
            await client.disconnect()
            self.db.close()

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.db.close()
        except Exception:
            pass  # Suppress errors during cleanup
