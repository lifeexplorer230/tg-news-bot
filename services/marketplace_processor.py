"""Обработчик новостей маркетплейсов с поддержкой Ozon и Wildberries"""
from datetime import timedelta

from telethon import TelegramClient

from database.db import Database
from models.marketplace import Marketplace
from services.embeddings import EmbeddingService
from services.gemini_client import GeminiClient
from utils.config import Config
from utils.logger import get_logger
from utils.timezone import now_msk

logger = get_logger(__name__)


class MarketplaceProcessor:
    """Процессор новостей для маркетплейсов (Ozon и Wildberries)"""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path)
        self._embedding_service: EmbeddingService | None = None
        self._gemini_client: GeminiClient | None = None
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

        raw_marketplaces = config.get("marketplaces", [])
        if isinstance(raw_marketplaces, dict):
            raw_marketplaces = [
                {
                    "name": name,
                    **(raw_marketplaces[name] or {}),
                }
                for name in raw_marketplaces
            ]

        self.marketplaces: dict[str, Marketplace] = {}
        for mp_cfg in raw_marketplaces:
            if not isinstance(mp_cfg, dict):
                continue
            data = dict(mp_cfg)
            data.setdefault("enabled", True)
            try:
                marketplace = Marketplace(**data)
            except TypeError as exc:
                logger.error(f"Некорректная конфигурация маркетплейса {mp_cfg}: {exc}")
                continue
            marketplace.combined_exclude_keywords_lower = list(
                dict.fromkeys(marketplace.exclude_keywords_lower + self.global_exclude_keywords)
            )
            self.marketplaces[marketplace.name] = marketplace

        if not self.marketplaces:
            logger.warning("В конфигурации не найдено ни одного маркетплейса")

        self.all_exclude_keywords_lower = set(self.global_exclude_keywords)
        for marketplace in self.marketplaces.values():
            self.all_exclude_keywords_lower.update(marketplace.combined_exclude_keywords_lower)

        self.marketplace_names = list(self.marketplaces.keys())

        default_channel = next(
            (mp.target_channel for mp in self.marketplaces.values() if mp.target_channel),
            None,
        )

        self.all_digest_enabled = config.get("channels.all_digest.enabled", True)
        self.all_digest_channel = config.get(
            "channels.all_digest.target_channel",
            default_channel,
        )
        counts_config = config.get("channels.all_digest.category_counts", {})
        self.all_digest_counts = {
            "wildberries": counts_config.get("wildberries", 5),
            "ozon": counts_config.get("ozon", 5),
            "general": counts_config.get("general", 5),
        }

        self.duplicate_threshold = config.get("processor.duplicate_threshold", 0.85)
        self.moderation_enabled = config.get("moderation.enabled", True)

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
            )
        return self._gemini_client

    async def process_marketplace(self, marketplace: str, client: TelegramClient):
        """Обработка новостей для конкретного маркетплейса"""

        if marketplace not in self.marketplaces:
            logger.error(f"Неизвестный маркетплейс: {marketplace}")
            return

        mp_config = self.marketplaces.get(marketplace)
        if mp_config is None:
            logger.error(f"Маркетплейс {marketplace} отсутствует в конфигурации")
            return

        if not mp_config.enabled:
            logger.info(f"Маркетплейс {marketplace} отключен в конфиге")
            return

        logger.info("=" * 80)
        logger.info(f"🛒 ОБРАБОТКА НОВОСТЕЙ: {marketplace.upper()}")
        logger.info("=" * 80)

        # ШАГ 1: Загружаем сообщения за последние 24 часа
        base_messages = self.db.get_unprocessed_messages(hours=24)
        logger.info(f"Загружено {len(base_messages)} необработанных сообщений")

        if not base_messages:
            logger.info(f"Нет новых сообщений для {marketplace}")
            return

        filtered_messages = self._filter_by_keywords(
            base_messages, mp_config.keywords_lower, mp_config.combined_exclude_keywords_lower
        )
        logger.info(f"После фильтрации по ключевым словам: {len(filtered_messages)} сообщений")

        if not filtered_messages:
            logger.info(f"Нет сообщений про {marketplace} после фильтрации")
            return

        # ШАГ 3: Проверка дубликатов
        unique_messages = await self.filter_duplicates(filtered_messages)
        logger.info(f"После проверки дубликатов: {len(unique_messages)} уникальных")

        if not unique_messages:
            logger.warning("Все сообщения являются дубликатами")
            return

        # ШАГ 4: Отбор и форматирование через Gemini (ОДИН ЗАПРОС!)
        formatted_posts = self.gemini.select_and_format_marketplace_news(
            unique_messages,
            marketplace=marketplace,
            top_n=mp_config.top_n,
            marketplace_display_name=mp_config.display_name or marketplace,
        )

        if not formatted_posts:
            for msg in unique_messages:
                self.db.mark_as_processed(msg["id"], rejection_reason="rejected_by_llm")
            logger.warning(f"Gemini не отобрал ни одной новости для {marketplace}")
            return

        logger.info(f"Gemini отобрал {len(formatted_posts)} новостей для {marketplace}")

        # Сортируем от самой важной к менее важной
        formatted_posts = sorted(formatted_posts, key=lambda x: x.get("score", 0), reverse=True)

        formatted_ids = {post["source_message_id"] for post in formatted_posts}
        for msg in unique_messages:
            if msg["id"] not in formatted_ids:
                self.db.mark_as_processed(msg["id"], rejection_reason="rejected_by_llm")

        # Помечаем сообщения как обработанные
        for post in formatted_posts:
            self.db.mark_as_processed(post["source_message_id"], gemini_score=post.get("score"))

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

        logger.info(f"✅ Обработка {marketplace} завершена!")

    def _filter_by_keywords(
        self, messages: list[dict], keywords_lower: list[str], exclude_keywords_lower: list[str]
    ) -> list[dict]:
        """Фильтрация сообщений по ключевым словам"""
        filtered = []

        for msg in messages:
            text_lower = msg["text"].lower()

            # Проверяем исключающие слова
            if exclude_keywords_lower and any(
                exclude in text_lower for exclude in exclude_keywords_lower
            ):
                self.db.mark_as_processed(
                    msg["id"], rejection_reason="rejected_by_exclude_keywords"
                )
                continue

            # Проверяем включающие слова
            if keywords_lower and not any(keyword in text_lower for keyword in keywords_lower):
                self.db.mark_as_processed(
                    msg["id"], rejection_reason="rejected_by_keywords_mismatch"
                )
                continue

            filtered.append(msg)

        return filtered

    async def filter_duplicates(self, messages: list[dict]) -> list[dict]:
        """Фильтрация дубликатов через embeddings"""
        unique = []

        for msg in messages:
            # Генерируем embedding
            embedding = self.embeddings.encode(msg["text"])

            # Проверяем на дубликаты
            is_duplicate = self.db.check_duplicate(embedding, self.duplicate_threshold)

            if is_duplicate:
                self.db.mark_as_processed(
                    msg["id"], is_duplicate=True, rejection_reason="is_duplicate"
                )
                continue

            unique.append(msg)

        return unique

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

        base_messages = self.db.get_unprocessed_messages(hours=24)
        logger.info(f"Загружено {len(base_messages)} необработанных сообщений")

        if not base_messages:
            logger.info("Нет новых сообщений")
            return

        # ШАГ 2: Фильтруем по глобальным исключающим словам и сразу отмечаем отклонённые
        filtered_messages = []
        for msg in base_messages:
            text_lower = msg["text"].lower()
            if self.all_exclude_keywords_lower and any(
                exclude in text_lower for exclude in self.all_exclude_keywords_lower
            ):
                self.db.mark_as_processed(
                    msg["id"], rejection_reason="rejected_by_exclude_keywords"
                )
                continue
            filtered_messages.append(msg)

        logger.info(f"После фильтрации исключений: {len(filtered_messages)} сообщений")

        if not filtered_messages:
            logger.info("Нет сообщений после фильтрации исключений")
            return

        # ШАГ 3: Проверка дубликатов
        unique_messages = await self.filter_duplicates(filtered_messages)
        logger.info(f"После проверки дубликатов: {len(unique_messages)} уникальных")

        if not unique_messages:
            logger.warning("Все сообщения являются дубликатами")
            return

        # ШАГ 4: Отбор по 3 категориям через Gemini (5+5+5=15 новостей)
        categories = self.gemini.select_three_categories(
            unique_messages,
            wb_count=self.all_digest_counts["wildberries"],
            ozon_count=self.all_digest_counts["ozon"],
            general_count=self.all_digest_counts["general"],
        )

        # Подсчитываем сколько получилось
        wb_count = len(categories.get("wildberries", []))
        ozon_count = len(categories.get("ozon", []))
        general_count = len(categories.get("general", []))
        total_count = wb_count + ozon_count + general_count

        logger.info(
            f"Gemini отобрал: WB={wb_count}, Ozon={ozon_count}, Общие={general_count}, Всего={total_count}"
        )

        selected_ids = {
            post["source_message_id"]
            for posts in categories.values()
            for post in posts
            if post.get("source_message_id")
        }

        if total_count == 0:
            logger.warning("Gemini не отобрал ни одной новости")
            for msg in unique_messages:
                self.db.mark_as_processed(msg["id"], rejection_reason="rejected_by_llm")
            return

        # ШАГ 5: Модерация (выбор 10 из 15)
        if self.moderation_enabled:
            approved_posts = await self.moderate_categories(client, categories)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                for msg_id in selected_ids:
                    self.db.mark_as_processed(msg_id, rejection_reason="rejected_by_moderator")
                return
        else:
            # Без модерации - берем все что есть
            approved_posts = (
                categories.get("wildberries", [])
                + categories.get("ozon", [])
                + categories.get("general", [])
            )

        approved_ids = {
            post.get("source_message_id")
            for post in approved_posts
            if post.get("source_message_id")
        }

        # Помечаем сообщения, которые прошли отбор Gemini, но не попали в итоговую публикацию
        rejected_after_moderation = selected_ids - approved_ids
        for msg_id in rejected_after_moderation:
            self.db.mark_as_processed(msg_id, rejection_reason="rejected_by_moderator")

        # Помечаем сообщения, которые Gemini не выбрал вовсе
        unique_ids = {msg["id"] for msg in unique_messages}
        not_selected_ids = unique_ids - selected_ids
        for msg_id in not_selected_ids:
            self.db.mark_as_processed(msg_id, rejection_reason="rejected_by_llm")

        # Помечаем сообщения как обработанные
        for post in approved_posts:
            self.db.mark_as_processed(post["source_message_id"], gemini_score=post.get("score"))

        # ШАГ 6: Публикация в канал
        target_channel = (
            self.all_digest_channel
            if self.all_digest_enabled and self.all_digest_channel
            else next(
                (mp.target_channel for mp in self.marketplaces.values() if mp.target_channel),
                None,
            )
        )
        await self.publish_digest(
            client,
            approved_posts,
            "маркетплейсы",
            target_channel,
            display_name="Маркетплейсы",
        )

        logger.info("✅ Обработка всех категорий завершена!")

    async def moderate_categories(
        self, client: TelegramClient, categories: dict[str, list[dict]]
    ) -> list[dict]:
        """Интерактивная модерация: выбор 10 из 15 новостей (по категориям)"""

        # Объединяем все новости из 3 категорий
        all_posts = []

        # Добавляем категорию к каждому посту
        for cat_name, posts in categories.items():
            for post in posts:
                post["category"] = cat_name
                all_posts.append(post)

        total = len(all_posts)
        logger.info(f"📋 Отправка {total} новостей на модерацию (нужно выбрать 10)")

        # Присваиваем ID для модерации
        for idx, post in enumerate(all_posts, 1):
            post["moderation_id"] = idx

        # Формируем сообщение для модерации
        message = self._format_categories_moderation_message(categories)

        # Отправляем в личку
        personal_account = self.config.my_personal_account
        await client.send_message(personal_account, message)

        logger.info(f"✅ Сообщение для модерации отправлено в {personal_account}")

        # TODO: Здесь можно добавить логику ожидания ответа от модератора
        # Пока возвращаем первые 10 (автоматический отбор)
        # Сортируем по score и берем топ-10
        sorted_posts = sorted(all_posts, key=lambda x: x.get("score", 0), reverse=True)
        return sorted_posts[:10]

    def _format_categories_moderation_message(self, categories: dict[str, list[dict]]) -> str:
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
        lines.append("_Нужно выбрать 10 лучших из 15 новостей_\n")

        idx = 1

        # Категория Wildberries
        if categories.get("wildberries"):
            lines.append("📦 **WILDBERRIES**\n")
            for post in categories["wildberries"]:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        # Категория Ozon
        if categories.get("ozon"):
            lines.append("📦 **OZON**\n")
            for post in categories["ozon"]:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        # Категория Общие
        if categories.get("general"):
            lines.append("📦 **ОБЩИЕ**\n")
            for post in categories["general"]:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        lines.append("=" * 50)
        lines.append(f"📊 **Всего:** {idx-1} новостей\n")
        lines.append("**Инструкция:**")
        lines.append("Отправь номера для **ПУБЛИКАЦИИ** через пробел (10 штук)")
        lines.append("Например: `1 2 3 5 6 8 9 11 13 14`\n")
        lines.append("Или отправь `топ10` чтобы взять 10 лучших по оценке автоматически")

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

        lines = [f"📌 Главные новости {header_name} за {date_str}\n"]

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
            emoji = number_emojis.get(idx, f"{idx}️⃣")
            lines.append(f"{emoji} **{post['title']}**\n")
            lines.append(f"{post['description']}\n")

            if post.get("source_link"):
                lines.append(f"{post['source_link']}\n")

        lines.append("_" * 36)
        lines.append(f"Подпишись на новости {header_name}")
        lines.append(target_channel)

        digest = "\n".join(lines)

        # Публикуем
        await client.send_message(target_channel, digest)
        logger.info(f"✅ Дайджест опубликован в {target_channel}")

        # Сохраняем embeddings
        for post in posts:
            embedding = self.embeddings.encode(post["text"])
            self.db.save_published(
                text=post["text"],
                embedding=embedding,
                source_message_id=post["source_message_id"],
                source_channel_id=post["source_channel_id"],
            )

        logger.info(f"💾 Сохранено {len(posts)} embeddings в БД")

    async def run(self, use_categories=True):
        """Запуск обработки для всех маркетплейсов

        Args:
            use_categories: Если True - использует новую 3-категорийную систему (5+5+5=15, выбор 10)
                           Если False - использует старую систему (отдельно Ozon и WB)
        """

        # Подключаемся к Telegram с отдельной сессией для processor
        # Это предотвращает конфликты с listener который использует основную сессию
        processor_session = self.config.get("telegram.session_name") + "_processor"
        client = TelegramClient(
            processor_session, self.config.telegram_api_id, self.config.telegram_api_hash
        )

        await client.start(phone=self.config.telegram_phone)

        try:
            if use_categories:
                # НОВАЯ СИСТЕМА: 3 категории (WB + Ozon + Общие)
                await self.process_all_categories(client)
            else:
                # СТАРАЯ СИСТЕМА: Обрабатываем каждый маркетплейс отдельно
                for marketplace in self.marketplace_names:
                    try:
                        await self.process_marketplace(marketplace, client)
                    except Exception as e:
                        logger.error(f"Ошибка обработки {marketplace}: {e}", exc_info=True)
        finally:
            await client.disconnect()
            self.db.close()
