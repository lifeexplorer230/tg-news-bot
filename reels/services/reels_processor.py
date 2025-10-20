"""
Процессор для генерации Reels сценариев из новостей

Обеспечивает полный цикл: получение новостей из БД → обогащение →
генерация сценариев → отправка на модерацию.
"""

import asyncio
import logging
from typing import List, Tuple, Optional
from datetime import datetime, timedelta

from telethon import TelegramClient

from database.db import Database
from reels.models.news import News, EnrichedNews
from reels.models.reels import ReelsScenario
from reels.services.perplexity_client import PerplexityClient
from reels.config.reels_config import ReelsConfig
from utils.config import Config

logger = logging.getLogger(__name__)


class ReelsProcessor:
    """Процессор для генерации Reels сценариев из новостей"""

    def __init__(self, config: Config):
        """
        Инициализация процессора

        Args:
            config: Основная конфигурация ТНБ
        """
        self.config = config
        self.reels_config = ReelsConfig(config)

        # Создать Perplexity клиент
        self.perplexity_client = PerplexityClient(self.reels_config)

        # Получить БД из профиля источника
        source_profile = self.reels_config.db_source_profile
        db_path = config.get(f"paths.data_dir", "./data") + f"/{source_profile}_news.db"
        self.db = Database(db_path)

        logger.info(f"ReelsProcessor инициализирован: db={db_path}, profile={source_profile}")

    async def process_latest_news(
        self,
        limit: Optional[int] = None,
        category: Optional[str] = None
    ) -> Tuple[List[EnrichedNews], List[ReelsScenario]]:
        """
        Обработать последние новости из БД

        Args:
            limit: Количество новостей для обработки (None = из конфига)
            category: Фильтр по категории (None = все)

        Returns:
            Кортеж (обогащенные новости, сценарии Reels)
        """
        limit = limit or self.reels_config.news_limit

        logger.info(f"Начало обработки последних {limit} новостей")

        # Получить новости из БД
        news_list = await self._fetch_news_from_db(limit, category)

        if not news_list:
            logger.warning("Нет новостей для обработки")
            return [], []

        logger.info(f"Получено {len(news_list)} новостей из БД")

        enriched_news = []
        scenarios = []

        # Обработать каждую новость
        for i, news in enumerate(news_list, 1):
            try:
                logger.info(f"Обработка новости {i}/{len(news_list)}: {news.title[:50]}...")

                enriched, scenario = await self.perplexity_client.process_news_to_reels(news)

                enriched_news.append(enriched)
                scenarios.append(scenario)

                logger.info(f"✅ Обработана новость {i}/{len(news_list)}: {news.id}")

                # Небольшая пауза между обработкой для rate limiting
                if i < len(news_list):
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(
                    f"❌ Ошибка обработки новости {news.id}: {e}",
                    exc_info=True
                )
                continue

        logger.info(
            f"Обработка завершена. Успешно: {len(scenarios)}/{len(news_list)} "
            f"({len(scenarios)/len(news_list)*100:.1f}%)"
        )

        return enriched_news, scenarios

    async def _fetch_news_from_db(
        self,
        limit: int,
        category: Optional[str]
    ) -> List[News]:
        """
        Получить новости из БД ТНБ

        Args:
            limit: Количество новостей
            category: Фильтр по категории

        Returns:
            Список новостей
        """
        table = self.reels_config.db_source_table
        days_back = self.reels_config.db_source_days_back

        # Вычислить дату начала
        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        logger.info(f"Получение новостей из таблицы {table}, дата >= {date_from}, лимит={limit}")

        # Запрос к БД (используем таблицу published из ТНБ)
        query = f"""
            SELECT
                id,
                title,
                content as summary,
                channel as source,
                created_at as published_date
            FROM {table}
            WHERE date(created_at) >= date(?)
            ORDER BY created_at DESC
            LIMIT ?
        """

        try:
            cursor = self.db.conn.cursor()
            cursor.execute(query, (date_from, limit))
            rows = cursor.fetchall()

            news_list = []
            for row in rows:
                news = News(
                    id=str(row[0]),
                    title=row[1] or "Без заголовка",
                    summary=(row[2] or "")[:500],  # Ограничить summary
                    source=row[3] or "Неизвестный источник",
                    published_date=row[4] or datetime.now().isoformat(),
                    category=category
                )
                news_list.append(news)

            logger.info(f"Получено {len(news_list)} новостей из БД")
            return news_list

        except Exception as e:
            logger.error(f"Ошибка получения новостей из БД: {e}", exc_info=True)
            return []

    def format_for_telegram(self, scenario: ReelsScenario) -> str:
        """
        Форматировать сценарий для отправки в Telegram

        Args:
            scenario: Сценарий Reels

        Returns:
            Форматированный текст для Telegram
        """
        format_type = self.reels_config.telegram_output_format

        if format_type == "compact":
            return self._format_compact(scenario)
        else:
            return self._format_detailed(scenario)

    def _format_detailed(self, scenario: ReelsScenario) -> str:
        """Детальное форматирование сценария"""
        formatted = f"""
🎬 **СЦЕНАРИЙ REELS: {scenario.title}**

📝 **ID новости:** `{scenario.news_id}`
⏱️ **Длительность:** {scenario.duration} секунд

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**🎯 HOOK (0-3 сек):**
{scenario.script.hook}

**📢 MAIN CONTENT (3-25 сек):**
{scenario.script.main_content}

**👉 CTA (25-30 сек):**
{scenario.script.cta}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**🎨 ВИЗУАЛЬНЫЕ ПРЕДЛОЖЕНИЯ:**
{self._format_list(scenario.visual_suggestions)}

**#️⃣ ХЭШТЕГИ:**
{scenario.get_formatted_hashtags()}

**🎵 НАСТРОЕНИЕ МУЗЫКИ:** {scenario.music_mood}

**👥 ЦЕЛЕВАЯ АУДИТОРИЯ:** {scenario.target_audience}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Символов в скрипте: {scenario.get_total_script_length()}
"""
        return formatted.strip()

    def _format_compact(self, scenario: ReelsScenario) -> str:
        """Компактное форматирование сценария"""
        formatted = f"""
🎬 **{scenario.title}**

**Hook:** {scenario.script.hook}
**Content:** {scenario.script.main_content[:100]}...
**CTA:** {scenario.script.cta}

{scenario.get_formatted_hashtags()}
"""
        return formatted.strip()

    def _format_list(self, items: List[str]) -> str:
        """Форматировать список с буллетами"""
        return '\n'.join(f"• {item}" for item in items)

    async def send_to_moderation(self, scenarios: List[ReelsScenario]):
        """
        Отправить сценарии в Telegram для модерации

        Args:
            scenarios: Список сценариев для отправки
        """
        if not self.reels_config.telegram_output_enabled:
            logger.info("Отправка в Telegram отключена в конфигурации")
            return

        channel = self.reels_config.telegram_output_channel
        if not channel:
            logger.warning("Telegram канал не настроен (output.telegram.channel)")
            return

        logger.info(f"Отправка {len(scenarios)} сценариев в {channel}")

        try:
            # Использовать TelegramClient из ТНБ
            async with TelegramClient(
                self.reels_config.telegram_session_file,
                self.reels_config.telegram_api_id,
                self.reels_config.telegram_api_hash
            ) as client:
                for i, scenario in enumerate(scenarios, 1):
                    try:
                        formatted = self.format_for_telegram(scenario)

                        await client.send_message(channel, formatted)

                        logger.info(
                            f"✅ Отправлен сценарий {i}/{len(scenarios)} "
                            f"для новости {scenario.news_id}"
                        )

                        # Rate limiting: 1 сообщение в секунду
                        if i < len(scenarios):
                            await asyncio.sleep(1)

                    except Exception as e:
                        logger.error(
                            f"❌ Ошибка отправки сценария {scenario.news_id}: {e}",
                            exc_info=True
                        )
                        continue

                logger.info(f"✅ Отправка завершена: {len(scenarios)} сценариев отправлено")

        except Exception as e:
            logger.error(f"Ошибка при работе с Telegram клиентом: {e}", exc_info=True)
            raise

    async def run(self):
        """
        Запустить полный цикл обработки

        Это основной метод для запуска процессора.
        """
        logger.info("=" * 80)
        logger.info("🎬 ЗАПУСК REELS PROCESSOR")
        logger.info("=" * 80)

        try:
            # Валидация конфигурации
            self.reels_config.validate()

            # Получить параметры обработки
            limit = self.reels_config.news_limit
            category = self.reels_config.filter_by_category

            if category:
                logger.info(f"Фильтр по категориям: {category}")

            # Обработать новости
            enriched_news, scenarios = await self.process_latest_news(limit, None)

            if scenarios:
                # Отправить на модерацию
                await self.send_to_moderation(scenarios)

                logger.info("=" * 80)
                logger.info(f"✅ ОБРАБОТКА ЗАВЕРШЕНА: {len(scenarios)} сценариев создано")
                logger.info("=" * 80)
            else:
                logger.warning("⚠️ Нет сценариев для отправки")

        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении ReelsProcessor: {e}", exc_info=True)
            raise
