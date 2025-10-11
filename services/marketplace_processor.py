"""Обработчик новостей маркетплейсов с поддержкой Ozon и Wildberries"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from telethon import TelegramClient

from database.db import Database
from services.embeddings import EmbeddingService
from services.gemini_client import GeminiClient
from utils.logger import get_logger
from utils.config import Config
from utils.timezone import now_msk

logger = get_logger(__name__)


class MarketplaceProcessor:
    """Процессор новостей для маркетплейсов (Ozon и Wildberries)"""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path)
        self.embeddings = EmbeddingService()
        self.gemini = GeminiClient(
            api_key=config.gemini_api_key,
            model_name=config.get('gemini.model')
        )

        # Настройки для каждого маркетплейса
        self.marketplaces = {
            'ozon': {
                'enabled': config.get('channels.ozon.enabled', True),
                'top_n': config.get('channels.ozon.top_n', 10),
                'target_channel': config.get('channels.ozon.target_channel'),
                'keywords': config.get('channels.ozon.keywords', []),
                'exclude_keywords': config.get('channels.ozon.exclude_keywords', [])
            },
            'wildberries': {
                'enabled': config.get('channels.wildberries.enabled', True),
                'top_n': config.get('channels.wildberries.top_n', 10),
                'target_channel': config.get('channels.wildberries.target_channel'),
                'keywords': config.get('channels.wildberries.keywords', []),
                'exclude_keywords': config.get('channels.wildberries.exclude_keywords', [])
            }
        }

        self.all_digest_enabled = config.get('channels.all_digest.enabled', True)
        self.all_digest_channel = config.get(
            'channels.all_digest.target_channel',
            self.marketplaces['ozon']['target_channel']
        )

        self.duplicate_threshold = config.get('processor.duplicate_threshold', 0.85)
        self.moderation_enabled = config.get('moderation.enabled', True)

    async def process_marketplace(self, marketplace: str, client: TelegramClient):
        """Обработка новостей для конкретного маркетплейса"""

        if marketplace not in self.marketplaces:
            logger.error(f"Неизвестный маркетплейс: {marketplace}")
            return

        mp_config = self.marketplaces[marketplace]

        if not mp_config['enabled']:
            logger.info(f"Маркетплейс {marketplace} отключен в конфиге")
            return

        logger.info(f"=" * 80)
        logger.info(f"🛒 ОБРАБОТКА НОВОСТЕЙ: {marketplace.upper()}")
        logger.info(f"=" * 80)

        # ШАГ 1: Загружаем сообщения за последние 24 часа
        messages = self.db.get_unprocessed_messages(hours=24)
        logger.info(f"Загружено {len(messages)} необработанных сообщений")

        if not messages:
            logger.info(f"Нет новых сообщений для {marketplace}")
            return

        # ШАГ 2: Фильтруем по ключевым словам маркетплейса
        filtered_messages = self._filter_by_keywords(
            messages,
            mp_config['keywords'],
            mp_config['exclude_keywords']
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
            top_n=mp_config['top_n']
        )

        if not formatted_posts:
            for msg in unique_messages:
                self.db.mark_as_processed(
                    msg['id'],
                    rejection_reason='rejected_by_llm'
                )
            logger.warning(f"Gemini не отобрал ни одной новости для {marketplace}")
            return

        logger.info(f"Gemini отобрал {len(formatted_posts)} новостей для {marketplace}")

        # Сортируем от самой важной к менее важной
        formatted_posts = sorted(formatted_posts, key=lambda x: x.get('score', 0), reverse=True)

        formatted_ids = {post['source_message_id'] for post in formatted_posts}
        for msg in unique_messages:
            if msg['id'] not in formatted_ids:
                self.db.mark_as_processed(
                    msg['id'],
                    rejection_reason='rejected_by_llm'
                )

        # Помечаем сообщения как обработанные
        for post in formatted_posts:
            self.db.mark_as_processed(post['source_message_id'], gemini_score=post.get('score'))

        # ШАГ 5: Модерация (если включена)
        if self.moderation_enabled:
            approved_posts = await self.moderate_posts(client, formatted_posts, marketplace)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                return
        else:
            approved_posts = formatted_posts

        # ШАГ 6: Публикация
        await self.publish_digest(client, approved_posts, marketplace, mp_config['target_channel'])

        logger.info(f"✅ Обработка {marketplace} завершена!")

    def _filter_by_keywords(
        self,
        messages: List[Dict],
        keywords: List[str],
        exclude_keywords: List[str]
    ) -> List[Dict]:
        """Фильтрация сообщений по ключевым словам"""
        filtered = []

        for msg in messages:
            text_lower = msg['text'].lower()

            # Проверяем исключающие слова
            if any(exclude.lower() in text_lower for exclude in exclude_keywords):
                continue

            # Проверяем включающие слова
            if any(keyword.lower() in text_lower for keyword in keywords):
                filtered.append(msg)

        filtered_ids = {msg['id'] for msg in filtered}
        for msg in messages:
            if msg['id'] in filtered_ids:
                continue

            text_lower = msg['text'].lower()
            if any(exclude.lower() in text_lower for exclude in exclude_keywords):
                self.db.mark_as_processed(
                    msg['id'],
                    rejection_reason='rejected_by_exclude_keywords'
                )
            elif keywords and not any(keyword.lower() in text_lower for keyword in keywords):
                self.db.mark_as_processed(
                    msg['id'],
                    rejection_reason='rejected_by_keywords_mismatch'
                )

        return filtered

    async def filter_duplicates(self, messages: List[Dict]) -> List[Dict]:
        """Фильтрация дубликатов через embeddings"""
        unique = []

        for msg in messages:
            # Генерируем embedding
            embedding = self.embeddings.encode(msg['text'])

            # Проверяем на дубликаты
            is_duplicate = self.db.check_duplicate(embedding, self.duplicate_threshold)

            if is_duplicate:
                self.db.mark_as_processed(
                    msg['id'],
                    is_duplicate=True,
                    rejection_reason='is_duplicate'
                )
                continue

            unique.append(msg)

        return unique

    async def moderate_posts(
        self,
        client: TelegramClient,
        posts: List[Dict],
        marketplace: str
    ) -> List[Dict]:
        """Отправка новостей на модерацию через Telegram"""

        logger.info(f"📋 Отправка {len(posts)} новостей на модерацию ({marketplace})")

        # Присваиваем ID для модерации
        for idx, post in enumerate(posts, 1):
            post['moderation_id'] = idx

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

        logger.info(f"=" * 80)
        logger.info(f"📦 ОБРАБОТКА НОВОСТЕЙ: ВСЕ КАТЕГОРИИ (3-КАТЕГОРИЙНАЯ СИСТЕМА)")
        logger.info(f"=" * 80)

        # ШАГ 1: Загружаем ВСЕ необработанные сообщения за последние 24 часа
        messages = self.db.get_unprocessed_messages(hours=24)
        logger.info(f"Загружено {len(messages)} необработанных сообщений")

        if not messages:
            logger.info("Нет новых сообщений")
            return

        # ШАГ 2: Объединяем все exclude_keywords из обоих маркетплейсов
        all_exclude_keywords = set()
        for mp_config in self.marketplaces.values():
            all_exclude_keywords.update(mp_config['exclude_keywords'])

        # Фильтруем по исключающим словам
        filtered_messages = []
        for msg in messages:
            text_lower = msg['text'].lower()
            if not any(exclude.lower() in text_lower for exclude in all_exclude_keywords):
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
            wb_count=5,
            ozon_count=5,
            general_count=5
        )

        # Подсчитываем сколько получилось
        wb_count = len(categories.get('wildberries', []))
        ozon_count = len(categories.get('ozon', []))
        general_count = len(categories.get('general', []))
        total_count = wb_count + ozon_count + general_count

        logger.info(f"Gemini отобрал: WB={wb_count}, Ozon={ozon_count}, Общие={general_count}, Всего={total_count}")

        if total_count == 0:
            logger.warning("Gemini не отобрал ни одной новости")
            return

        # ШАГ 5: Модерация (выбор 10 из 15)
        if self.moderation_enabled:
            approved_posts = await self.moderate_categories(client, categories)

            if not approved_posts:
                logger.warning("Все новости отклонены на этапе модерации")
                return
        else:
            # Без модерации - берем все что есть
            approved_posts = (
                categories.get('wildberries', []) +
                categories.get('ozon', []) +
                categories.get('general', [])
            )

        # Помечаем сообщения как обработанные
        for post in approved_posts:
            self.db.mark_as_processed(post['source_message_id'], gemini_score=post.get('score'))

        # ШАГ 6: Публикация в канал
        target_channel = (
            self.all_digest_channel
            if self.all_digest_enabled and self.all_digest_channel
            else self.marketplaces['ozon']['target_channel']
        )
        await self.publish_digest(client, approved_posts, "Маркетплейсы", target_channel)

        logger.info(f"✅ Обработка всех категорий завершена!")

    async def moderate_categories(
        self,
        client: TelegramClient,
        categories: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """Интерактивная модерация: выбор 10 из 15 новостей (по категориям)"""

        # Объединяем все новости из 3 категорий
        all_posts = []

        # Добавляем категорию к каждому посту
        for cat_name, posts in categories.items():
            for post in posts:
                post['category'] = cat_name
                all_posts.append(post)

        total = len(all_posts)
        logger.info(f"📋 Отправка {total} новостей на модерацию (нужно выбрать 10)")

        # Присваиваем ID для модерации
        for idx, post in enumerate(all_posts, 1):
            post['moderation_id'] = idx

        # Формируем сообщение для модерации
        message = self._format_categories_moderation_message(categories)

        # Отправляем в личку
        personal_account = self.config.my_personal_account
        await client.send_message(personal_account, message)

        logger.info(f"✅ Сообщение для модерации отправлено в {personal_account}")

        # TODO: Здесь можно добавить логику ожидания ответа от модератора
        # Пока возвращаем первые 10 (автоматический отбор)
        # Сортируем по score и берем топ-10
        sorted_posts = sorted(all_posts, key=lambda x: x.get('score', 0), reverse=True)
        return sorted_posts[:10]

    def _format_categories_moderation_message(self, categories: Dict[str, List[Dict]]) -> str:
        """Форматирование сообщения для модерации 3-категорийной системы"""

        number_emojis = {
            1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
            6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟",
            11: "1️⃣1️⃣", 12: "1️⃣2️⃣", 13: "1️⃣3️⃣", 14: "1️⃣4️⃣", 15: "1️⃣5️⃣"
        }

        lines = [f"📋 **МОДЕРАЦИЯ: ВСЕ КАТЕГОРИИ**"]
        lines.append(f"_Нужно выбрать 10 лучших из 15 новостей_\n")

        idx = 1

        # Категория Wildberries
        if categories.get('wildberries'):
            lines.append("📦 **WILDBERRIES**\n")
            for post in categories['wildberries']:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        # Категория Ozon
        if categories.get('ozon'):
            lines.append("📦 **OZON**\n")
            for post in categories['ozon']:
                emoji = number_emojis.get(idx, f"{idx}.")
                lines.append(f"{emoji} **{post['title']}**")
                lines.append(f"_{post['description'][:100]}..._")
                lines.append(f"⭐ {post.get('score', 0)}/10\n")
                idx += 1

        # Категория Общие
        if categories.get('general'):
            lines.append("📦 **ОБЩИЕ**\n")
            for post in categories['general']:
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

    def _format_moderation_message(self, posts: List[Dict], marketplace: str) -> str:
        """Форматирование сообщения для модерации"""

        number_emojis = {
            1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
            6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"
        }

        lines = [f"📋 **МОДЕРАЦИЯ: {marketplace.upper()}**"]
        lines.append(f"_(Отсортировано по важности)_\n")

        for post in posts:
            idx = post['moderation_id']
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
        posts: List[Dict],
        marketplace: str,
        target_channel: str
    ):
        """Публикация дайджеста в канал"""

        logger.info(f"📤 Публикация {len(posts)} новостей в {target_channel}")

        # Формируем дайджест
        yesterday = now_msk() - timedelta(days=1)
        date_str = yesterday.strftime("%d-%m-%Y")

        lines = [f"📌 Главные новости {marketplace.upper()} за {date_str}\n"]

        number_emojis = {
            1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
            6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"
        }

        for idx, post in enumerate(posts, 1):
            emoji = number_emojis.get(idx, f"{idx}️⃣")
            lines.append(f"{emoji} **{post['title']}**\n")
            lines.append(f"{post['description']}\n")

            if post.get('source_link'):
                lines.append(f"{post['source_link']}\n")

        lines.append("_" * 36)
        lines.append(f"Подпишись на новости {marketplace.upper()}")
        lines.append(target_channel)

        digest = "\n".join(lines)

        # Публикуем
        await client.send_message(target_channel, digest)
        logger.info(f"✅ Дайджест опубликован в {target_channel}")

        # Сохраняем embeddings
        for post in posts:
            embedding = self.embeddings.encode(post['text'])
            self.db.save_published(
                text=post['text'],
                embedding=embedding,
                source_message_id=post['source_message_id'],
                source_channel_id=post['source_channel_id']
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
        processor_session = self.config.get('telegram.session_name') + '_processor'
        client = TelegramClient(
            processor_session,
            self.config.telegram_api_id,
            self.config.telegram_api_hash
        )

        await client.start(phone=self.config.telegram_phone)

        try:
            if use_categories:
                # НОВАЯ СИСТЕМА: 3 категории (WB + Ozon + Общие)
                await self.process_all_categories(client)
            else:
                # СТАРАЯ СИСТЕМА: Обрабатываем каждый маркетплейс отдельно
                for marketplace in ['ozon', 'wildberries']:
                    try:
                        await self.process_marketplace(marketplace, client)
                    except Exception as e:
                        logger.error(f"Ошибка обработки {marketplace}: {e}", exc_info=True)
        finally:
            await client.disconnect()
            self.db.close()
