"""Универсальный процессор новостей с поддержкой категорий"""

import asyncio
from datetime import timedelta

import numpy as np
from telethon import TelegramClient

from database.db import Database
from models.category import Category
from services.embeddings import EmbeddingService
from services.gemini_client import GeminiClient
from utils.config import Config
from utils.logger import get_logger
from utils.telegram_helpers import safe_connect
from utils.timezone import now_msk

logger = get_logger(__name__)


class NewsProcessor:
    """Универсальный процессор новостей с поддержкой категорий"""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path, **config.database_settings())
        self._embedding_service: EmbeddingService | None = None
        self._gemini_client: GeminiClient | None = None

        # Кэш для оптимизации (CR-H1)
        self._cached_published_embeddings: list[tuple[int, any]] | None = None
        # QA-7: _cached_base_messages удалён как мёртвый код (не используется)

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

        self.publication_header_template = config.get(
            "publication.header_template",
            "📰 Главные новости за {date}",
        )
        self.publication_footer_template = config.get("publication.footer_template", "")
        self.publication_preview_channel = config.get("publication.preview_channel")
        self.publication_notify_account = config.get("publication.notify_account")

        self.duplicate_threshold = config.get("processor.duplicate_threshold", 0.85)
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
        self.moderation_enabled = config.get("moderation.enabled", True)
        self.moderation_timeout_hours = config.get("moderation.timeout_hours", 2)

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

    async def process_category(
        self, marketplace: str, client: TelegramClient, base_messages: list[dict] | None = None
    ):
        """
        Обработка новостей для конкретной категории

        Args:
            marketplace: Название категории (параметр сохранён для backwards compatibility)
            client: Telegram client
            base_messages: Кэшированные сообщения (оптимизация CR-H1). Если None - загружаются из БД
        """

        if marketplace not in self.categories:
            logger.error(f"Неизвестная категория: {marketplace}")
            return

        mp_config = self.categories.get(marketplace)
        if mp_config is None:
            logger.error(f"Категория {marketplace} отсутствует в конфигурации")
            return

        if not mp_config.enabled:
            logger.info(f"Категория {marketplace} отключена в конфиге")
            return

        logger.info("=" * 80)
        logger.info(f"📰 ОБРАБОТКА КАТЕГОРИИ: {marketplace.upper()}")
        logger.info("=" * 80)

        # ШАГ 1: Загружаем сообщения (из кэша или БД)
        if base_messages is None:
            # Sprint 6.3: Неблокирующий доступ к БД
            base_messages = await asyncio.to_thread(self.db.get_unprocessed_messages, hours=24)
            logger.info(f"Загружено {len(base_messages)} необработанных сообщений из БД")
        else:
            logger.info(f"Используем {len(base_messages)} кэшированных сообщений (CR-H1)")

        if not base_messages:
            logger.info(f"Нет новых сообщений для {marketplace}")
            return

        # Словарь для отслеживания причин отклонения
        all_rejected = {}

        # ШАГ 2: Фильтрация по ключевым словам
        filtered_messages, rejected_by_keywords = self._filter_by_keywords(
            base_messages, mp_config.keywords_lower, mp_config.combined_exclude_keywords_lower
        )
        all_rejected.update(rejected_by_keywords)
        logger.info(f"После фильтрации по ключевым словам: {len(filtered_messages)} сообщений")

        if not filtered_messages:
            # Помечаем все отфильтрованные как processed
            # Sprint 6.4: Батч-обработка вместо N вызовов
            updates = [
                {'message_id': msg_id, 'rejection_reason': reason}
                for msg_id, reason in all_rejected.items()
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            logger.info(f"Нет сообщений про {marketplace} после фильтрации")
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

        # ШАГ 4: Отбор и форматирование через Gemini (ОДИН ЗАПРОС!)
        # Sprint 6.5: Неблокирующие LLM вызовы
        formatted_posts = await asyncio.to_thread(
            self.gemini.select_and_format_marketplace_news,
            unique_messages,
            marketplace=marketplace,
            top_n=mp_config.top_n,
            marketplace_display_name=mp_config.display_name or marketplace,
        )

        if not formatted_posts:
            # Sprint 6.4: Батч-обработка вместо N вызовов
            updates = [
                {'message_id': msg["id"], 'rejection_reason': "rejected_by_llm"}
                for msg in unique_messages
            ]
            await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
            logger.warning(f"Gemini не отобрал ни одной новости для {marketplace}")
            return

        logger.info(f"Gemini отобрал {len(formatted_posts)} новостей для {marketplace}")

        # Сортируем от самой важной к менее важной
        formatted_posts = sorted(formatted_posts, key=lambda x: x.get("score", 0), reverse=True)

        formatted_ids = {post["source_message_id"] for post in formatted_posts}
        # Sprint 6.4: Батч-обработка вместо N вызовов
        updates = [
            {'message_id': msg["id"], 'rejection_reason': "rejected_by_llm"}
            for msg in unique_messages
            if msg["id"] not in formatted_ids
        ]
        await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # Помечаем сообщения как обработанные
        # Sprint 6.4: Батч-обработка вместо N вызовов
        updates = [
            {'message_id': post["source_message_id"], 'gemini_score': post.get("score")}
            for post in formatted_posts
        ]
        await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # ШАГ 5: Модерация (если включена)
        if self.moderation_enabled:
            approved_posts = await self.moderate_posts(client, formatted_posts, marketplace)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                return
        else:
            approved_posts = formatted_posts

        # ШАГ 6: Публикация
        await self.publish_digest(
            client,
            approved_posts,
            marketplace,
            mp_config.target_channel,
            display_name=mp_config.display_name or marketplace,
        )

        # ШАГ 7: Помечаем все отфильтрованные сообщения как processed
        # (которые не были помечены ранее)
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

        logger.info(f"✅ Обработка {marketplace} завершена!")

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

        Returns:
            Tuple of (unique_messages, rejected_reasons)
            where rejected_reasons maps message_id -> rejection_reason
        """
        unique = []
        rejected = {}

        if not messages:
            return unique, rejected

        # CR-H1: Загружаем published embeddings один раз и кэшируем
        # Sprint 6.3: Неблокирующий доступ к БД
        if self._cached_published_embeddings is None:
            self._cached_published_embeddings = await asyncio.to_thread(self.db.get_published_embeddings, days=60)
            logger.debug(f"Загружено {len(self._cached_published_embeddings)} published embeddings в кэш")

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

        # Проверяем каждое сообщение на дубликаты
        for msg, embedding in zip(messages, embeddings_array):
            # Проверяем на дубликаты (inline вместо db.check_duplicate)
            # Sprint 6.3.4: удалён неиспользуемый аргумент published_embeddings
            is_duplicate = self._check_duplicate_inline(
                embedding, self.duplicate_threshold
            )

            if is_duplicate:
                rejected[msg["id"]] = "is_duplicate"
                continue

            unique.append(msg)

        return unique, rejected

    def _update_published_cache(self, post_ids: list[int], embeddings: list[np.ndarray]):
        """
        QA-2: Обновить кэш published embeddings после публикации
        QA-4: Также обновляем матрицу embeddings для оптимизации дедупликации

        Инкрементально добавляет новые embeddings в кэш, чтобы последующие
        категории в том же запуске могли детектировать дубликаты.

        Args:
            post_ids: Список source_message_id опубликованных постов
            embeddings: Соответствующие embeddings
        """
        if self._cached_published_embeddings is None:
            # Кэш ещё не инициализирован - инициализируем
            self._cached_published_embeddings = []
            logger.debug("QA-2: Инициализирован кэш published embeddings")

        # Добавляем новые embeddings в кэш
        new_entries = list(zip(post_ids, embeddings))
        self._cached_published_embeddings.extend(new_entries)

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
        self, embedding: np.ndarray, threshold: float = 0.85
    ) -> bool:
        """
        Проверить дубликат inline без обращения к БД (оптимизация CR-H1)
        Оптимизировано (CR-C5): используем batch_cosine_similarity для векторизации
        Оптимизировано (QA-4): переиспользуем кэшированную матрицу вместо пересоздания
        Рефакторинг (Sprint 6.3.4): удалён неиспользуемый параметр published_embeddings

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

        # ШАГ 4: Отбор по категориям через Gemini (динамическая система)
        # Поддерживает любые категории из конфига, не только marketplace-специфичные
        # Sprint 6.5: Неблокирующие LLM вызовы
        categories = await asyncio.to_thread(
            self.gemini.select_by_categories,
            unique_messages,
            category_counts=self.all_digest_counts,
        )

        # Подсчитываем сколько получилось (динамически для всех категорий)
        category_stats = {cat: len(posts) for cat, posts in categories.items()}
        total_count = sum(category_stats.values())

        # Формируем красивый лог с категориями
        stats_str = ", ".join(f"{cat}={count}" for cat, count in category_stats.items())
        logger.info(f"Gemini отобрал: {stats_str}, Всего={total_count}")

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

        # ШАГ 5: Модерация (выбор 10 из 15)
        if self.moderation_enabled:
            approved_posts = await self.moderate_categories(client, categories)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                # Sprint 6.4: Батч-обработка вместо N вызовов
                updates = [
                    {'message_id': msg_id, 'rejection_reason': "rejected_by_moderator"}
                    for msg_id in selected_ids
                ]
                await asyncio.to_thread(self.db.mark_as_processed_batch, updates)
                return
        else:
            # Без модерации - берем все что есть (динамически для всех категорий)
            approved_posts = [post for posts in categories.values() for post in posts]

        approved_ids = {
            post.get("source_message_id")
            for post in approved_posts
            if post.get("source_message_id")
        }

        # Помечаем сообщения, которые прошли отбор Gemini, но не попали в итоговую публикацию
        # Sprint 6.4: Батч-обработка вместо N вызовов
        rejected_after_moderation = selected_ids - approved_ids
        updates = [
            {'message_id': msg_id, 'rejection_reason': "rejected_by_moderator"}
            for msg_id in rejected_after_moderation
        ]
        await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # Помечаем сообщения, которые Gemini не выбрал вовсе
        # Sprint 6.4: Батч-обработка вместо N вызовов
        unique_ids = {msg["id"] for msg in unique_messages}
        not_selected_ids = unique_ids - selected_ids
        updates = [
            {'message_id': msg_id, 'rejection_reason': "rejected_by_llm"}
            for msg_id in not_selected_ids
        ]
        await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # Помечаем сообщения как обработанные
        # Sprint 6.4: Батч-обработка вместо N вызовов
        updates = [
            {'message_id': post["source_message_id"], 'gemini_score': post.get("score")}
            for post in approved_posts
        ]
        await asyncio.to_thread(self.db.mark_as_processed_batch, updates)

        # ШАГ 6: Публикация в канал
        target_channel = (
            self.all_digest_channel
            if self.all_digest_enabled and self.all_digest_channel
            else next(
                (mp.target_channel for mp in self.categories.values() if mp.target_channel),
                None,
            )
        )
        await self.publish_digest(
            client,
            approved_posts,
            "категории",
            target_channel,
            display_name="Категории",
        )

        # ШАГ 7: Помечаем все отфильтрованные сообщения как processed
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

        logger.info("✅ Обработка всех категорий завершена!")

    async def _wait_for_moderation_response_retry(
        self, conv, total_posts: int
    ) -> list[int] | None:
        """
        Повторное ожидание ответа модератора (после некорректного ввода)

        Args:
            conv: Conversation объект
            total_posts: Общее количество новостей

        Returns:
            Список номеров для исключения или None если отмена
        """
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
                await conv.send_message(
                    "⚠️ Не удалось распознать номера. "
                    "Отправь номера через пробел (например: 1 2 3 5 6)"
                )
                # Рекурсивно ждем правильного ответа
                return await self._wait_for_moderation_response_retry(conv, total_posts)

            await conv.send_message(
                f"✅ Исключено {len(excluded_ids)} новостей: {', '.join(map(str, excluded_ids))}\n"
                f"Будет опубликовано: {total_posts - len(excluded_ids)} новостей"
            )
            return excluded_ids

        except Exception as e:
            logger.error(f"Ошибка при повторном ожидании ответа: {e}", exc_info=True)
            return None

    async def _wait_for_moderation_response(
        self, client: TelegramClient, personal_account: str, message: str, total_posts: int
    ) -> list[int] | None:
        """
        Ожидание ответа модератора (без таймаута)

        Args:
            client: Telegram клиент
            personal_account: Username модератора
            message: Сообщение для модерации
            total_posts: Общее количество новостей

        Returns:
            Список номеров для исключения или None если отмена
        """
        logger.info("⏳ Отправка на модерацию и ожидание ответа...")

        # Используем conversation API для отправки и ожидания ответа
        async with client.conversation(personal_account) as conv:
            try:
                # Отправляем сообщение модерации
                await conv.send_message(message)
                logger.info(f"✅ Сообщение отправлено модератору {personal_account}")

                # Ждем ответа с таймаутом (в секундах)
                timeout_seconds = self.moderation_timeout_hours * 3600
                logger.info(f"⏰ Ожидание ответа модератора (timeout: {self.moderation_timeout_hours}ч)")

                response = await conv.get_response(timeout=timeout_seconds)
                response_text = response.message.strip().lower()

                logger.info(f"📨 Получен ответ модератора: {response_text}")

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
                    # Удаляем возможные символы типа запятых
                    part = part.strip(",.")
                    if part.isdigit():
                        num = int(part)
                        if 1 <= num <= total_posts:
                            excluded_ids.append(num)
                        else:
                            logger.warning(f"Номер {num} вне диапазона 1-{total_posts}")

                if not excluded_ids:
                    await conv.send_message(
                        "⚠️ Не удалось распознать номера. "
                        "Отправь номера через пробел (например: 1 2 3 5 6)"
                    )
                    # Рекурсивно ждем правильного ответа (без повторной отправки message)
                    return await self._wait_for_moderation_response_retry(
                        conv, total_posts
                    )

                await conv.send_message(
                    f"✅ Исключено {len(excluded_ids)} новостей: {', '.join(map(str, excluded_ids))}\n"
                    f"Будет опубликовано: {total_posts - len(excluded_ids)} новостей"
                )
                return excluded_ids

            except asyncio.TimeoutError:
                # Timeout модерации - автоматически публикуем все новости
                logger.warning(
                    f"⏰ Timeout модерации ({self.moderation_timeout_hours}ч) - "
                    f"автоматическая публикация всех {total_posts} новостей"
                )
                try:
                    await conv.send_message(
                        f"⏰ Время модерации истекло ({self.moderation_timeout_hours}ч)\n"
                        f"✅ Все {total_posts} новостей будут опубликованы автоматически"
                    )
                except Exception:
                    pass  # Игнорируем ошибки отправки уведомления
                return []  # Пустой список = опубликовать все

            except Exception as e:
                logger.error(f"Ошибка при ожидании ответа модератора: {e}", exc_info=True)
                return None

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

        total = len(all_posts)
        exclude_goal = max(0, min(self.processor_exclude_count, total))
        logger.info(
            "📋 Отправка %s новостей на модерацию (нужно исключить %s)",
            total,
            exclude_goal,
        )

        # Присваиваем ID для модерации
        for idx, post in enumerate(all_posts, 1):
            post["moderation_id"] = idx

        # Формируем сообщение для модерации
        message = self._format_categories_moderation_message(categories, exclude_goal)

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
        self, categories: dict[str, list[dict]], exclude_goal: int
    ) -> str:
        """Форматирование сообщения для модерации 3-категорийной системы"""

        number_emojis = {
            1: "1️⃣",
            2: "2️⃣",
            3: "3️⃣",
            4: "4️⃣",
            5: "5️⃣",
            6: "6️⃣",
            7: "7️⃣",
            8: "8️⃣",
            9: "9️⃣",
            10: "🔟",
            11: "1️⃣1️⃣",
            12: "1️⃣2️⃣",
            13: "1️⃣3️⃣",
            14: "1️⃣4️⃣",
            15: "1️⃣5️⃣",
        }

        lines = ["📋 **МОДЕРАЦИЯ: ВСЕ КАТЕГОРИИ**"]
        if exclude_goal > 0:
            lines.append(
                f"_Нужно исключить {exclude_goal} новостей из {sum(len(v) for v in categories.values())}_\n"
            )
        else:
            lines.append("_При необходимости можно исключить новости, отправив их номера_\n")

        idx = 1

        # Динамически форматируем все категории (универсальная система)
        for category_name, posts in categories.items():
            if not posts:
                continue

            # Форматируем имя категории красиво
            display_name = category_name.upper().replace("_", " ")
            lines.append(f"📦 **{display_name}**\n")

            for post in posts:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        lines.append("=" * 50)
        lines.append(f"📊 **Всего:** {idx-1} новостей\n")
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

        number_emojis = {
            1: "1️⃣",
            2: "2️⃣",
            3: "3️⃣",
            4: "4️⃣",
            5: "5️⃣",
            6: "6️⃣",
            7: "7️⃣",
            8: "8️⃣",
            9: "9️⃣",
            10: "🔟",
        }

        lines = [f"📋 **МОДЕРАЦИЯ: {marketplace.upper()}**"]
        lines.append("_(Отсортировано по важности)_\n")

        for post in posts:
            idx = post["moderation_id"]
            emoji = number_emojis.get(idx, f"{idx}️⃣")

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
    def _ensure_post_fields(post: dict) -> dict:
        """
        QA-1: Fallback-форматирование для постов без title/description

        Гарантирует наличие обязательных полей в посте.
        Если title или description отсутствуют, извлекаются из text.

        Args:
            post: Словарь с данными поста

        Returns:
            Валидированный пост с гарантированными полями title, description
        """
        # Проверяем наличие обязательных полей
        if "title" not in post or not post["title"]:
            # Извлекаем title из text
            text = post.get("text", "")
            if text:
                # Берём первую строку или первые 7 слов
                lines = text.split("\n", 1)
                first_line = lines[0].strip()
                words = first_line.split()
                post["title"] = " ".join(words[:7]) if len(words) > 7 else first_line
            else:
                post["title"] = "Без заголовка"

        if "description" not in post or not post["description"]:
            # Извлекаем description из text
            text = post.get("text", "")
            if text:
                # Берём всё кроме первой строки, или первые 200 символов
                lines = text.split("\n", 1)
                if len(lines) > 1:
                    post["description"] = lines[1].strip()[:200]
                else:
                    # Если только одна строка, берём со 2го слова
                    words = text.split()
                    post["description"] = " ".join(words[7:]) if len(words) > 7 else text
            else:
                post["description"] = "Описание отсутствует"

        return post

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

        lines = [header_line.strip() + "\n"]

        number_emojis = {
            1: "1️⃣",
            2: "2️⃣",
            3: "3️⃣",
            4: "4️⃣",
            5: "5️⃣",
            6: "6️⃣",
            7: "7️⃣",
            8: "8️⃣",
            9: "9️⃣",
            10: "🔟",
        }

        for idx, post in enumerate(posts, 1):
            # QA-1: Гарантируем наличие title/description
            post = self._ensure_post_fields(post)

            emoji = number_emojis.get(idx, f"{idx}️⃣")
            lines.append(f"{emoji} **{post['title']}**\n")
            lines.append(f"{post['description']}\n")

            if post.get("source_link"):
                lines.append(f"{post['source_link']}\n")

        footer = self.publication_footer_template.strip()
        if footer:
            try:
                footer_text = footer.format(**context)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Не удалось подставить параметры в publication.footer_template: %s", exc
                )
                footer_text = footer
            lines.append(footer_text)

        digest = "\n".join(lines)

        preview_channel = (self.publication_preview_channel or "").strip()
        if preview_channel:
            try:
                await client.send_message(preview_channel, digest)
                logger.info("📄 Черновик дайджеста отправлен в %s", preview_channel)
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось отправить превью в %s: %s", preview_channel, exc)

        # Публикуем
        await client.send_message(target_channel, digest)
        logger.info(f"✅ Дайджест опубликован в {target_channel}")

        notify_account = (self.publication_notify_account or "").strip()
        if notify_account:
            try:
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
            await asyncio.to_thread(
                self.db.save_published,
                text=post["text"],
                embedding=embedding,
                source_message_id=post["source_message_id"],
                source_channel_id=post["source_channel_id"],
            )
            post_ids.append(post["source_message_id"])

        logger.info(f"💾 Сохранено {len(posts)} embeddings в БД")

        # QA-2: Обновляем кэш после публикации для детектирования дубликатов в последующих категориях
        self._update_published_cache(post_ids, list(embeddings_array))

    async def run(self, use_categories=True):
        """Запуск обработки для всех категорий

        Args:
            use_categories: Если True - использует новую 3-категорийную систему (5+5+5=15, выбор 10)
                           Если False - использует старую систему (обработка каждой категории отдельно)
        """

        # Подключаемся к Telegram с использованием основной сессии
        # Используем safe_connect для предотвращения FloodWait блокировок
        session_name = self.config.get("telegram.session_name")
        client = TelegramClient(
            session_name, self.config.telegram_api_id, self.config.telegram_api_hash
        )

        await safe_connect(client, session_name)

        try:
            if use_categories:
                # НОВАЯ СИСТЕМА: 3 категории (WB + Ozon + Общие)
                await self.process_all_categories(client)
            else:
                # СТАРАЯ СИСТЕМА: Обрабатываем каждую категорию отдельно

                # CR-H1: Загружаем сообщения ОДИН раз для всех категорий
                # Sprint 6.3: Неблокирующий доступ к БД
                base_messages = await asyncio.to_thread(self.db.get_unprocessed_messages, hours=24)
                logger.info(
                    f"📦 CR-H1: Загружено {len(base_messages)} сообщений (будут переиспользованы для {len(self.category_names)} категорий)"
                )

                for category_name in self.category_names:
                    try:
                        # Передаем кэшированные base_messages вместо повторного чтения из БД
                        await self.process_category(category_name, client, base_messages=base_messages)
                    except Exception as e:
                        logger.error(f"Ошибка обработки {category_name}: {e}", exc_info=True)
        finally:
            await client.disconnect()
            self.db.close()

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.db.close()
        except Exception:
            pass  # Suppress errors during cleanup
