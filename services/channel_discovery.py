"""
Модуль авторасширения каналов.
Берёт рекомендации Telegram у подписанных каналов,
проверяет тематику через Gemini и подписывается.
"""

import asyncio
import random
import re
from datetime import datetime, timedelta, UTC

import aiohttp
from bs4 import BeautifulSoup

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChatAdminRequiredError,
)
from telethon.tl.functions.channels import (
    GetChannelRecommendationsRequest,
    JoinChannelRequest,
    LeaveChannelRequest,
)
from telethon.tl.types import Channel

import google.generativeai as genai

from database.db import Database
from utils.config import Config
from utils.logger import setup_logger
from utils.telegram_helpers import safe_connect

logger = setup_logger(__name__)

# ── Промпты для Gemini по профилям ────────────────────────────────────

PROFILE_PROMPTS = {
    "ai": {
        "quick": (
            "Проанализируй название Telegram-канала.\n"
            "Название: {title}\n\n"
            "Вопрос: Судя по названию, этот канал может быть про ИИ-агентов, "
            "ИИ-сотрудников или внедрение искусственного интеллекта в бизнес?\n"
            "Ответь ТОЛЬКО одним словом: Да или Нет."
        ),
        "deep": (
            "Проанализируй последние посты из Telegram-канала «{title}».\n\n"
            "Посты:\n{posts}\n\n"
            "Вопрос: Этот канал регулярно публикует контент про ИИ-агентов, "
            "ИИ-сотрудников или внедрение искусственного интеллекта в бизнес?\n"
            "Ответь ТОЛЬКО одним словом: Да или Нет."
        ),
    },
    "marketplace": {
        "quick": (
            "Проанализируй название Telegram-канала.\n"
            "Название: {title}\n\n"
            "Вопрос: Судя по названию, этот канал может содержать полезную "
            "информацию для селлеров маркетплейсов (Wildberries, Ozon)?\n"
            "Ответь ТОЛЬКО одним словом: Да или Нет."
        ),
        "deep": (
            "Проанализируй последние посты из Telegram-канала «{title}».\n\n"
            "Посты:\n{posts}\n\n"
            "Вопрос: Этот канал регулярно публикует полезную информацию для "
            "селлеров маркетплейсов (Wildberries, Ozon)?\n"
            "Ответь ТОЛЬКО одним словом: Да или Нет."
        ),
    },
}

# ── Лимиты антиблокировки ─────────────────────────────────────────────

MAX_SUBSCRIPTIONS_PER_DAY = 20
MAX_UNSUBSCRIPTIONS_PER_DAY = 5
SUBSCRIBE_DELAY_MIN = 120   # между подписками
SUBSCRIBE_DELAY_MAX = 300
API_DELAY_MIN = 5            # между чтениями Telegram API
API_DELAY_MAX = 10
CHANNEL_ALIVE_DAYS = 14      # канал «мёртв» если последний пост старше
DEEP_CHECK_POSTS = 15        # постов для глубокой проверки
MAX_POSTS_TEXT_LEN = 4000    # обрезка текста постов для Gemini
MAX_CANDIDATES_PER_RUN = 50  # макс кандидатов на валидацию за запуск


class ChannelDiscovery:
    """Поиск новых каналов через рекомендации + валидация Gemini."""

    def __init__(self, config: Config):
        self.config = config
        self.profile = config.profile or "ai"
        self.db = Database(config.db_path, **config.database_settings())
        self.prompts = PROFILE_PROMPTS.get(self.profile, PROFILE_PROMPTS["ai"])

        # Telethon
        self.client = TelegramClient(
            config.get("telegram.session_name"),
            config.telegram_api_id,
            config.telegram_api_hash,
        )

        # Gemini
        genai.configure(api_key=config.gemini_api_key)
        self._gemini_model = genai.GenerativeModel(
            config.get("gemini.model", "gemini-2.0-flash"),
        )

        self._init_meta_table()

    # ── Инициализация БД ──────────────────────────────────────────────

    def _init_meta_table(self):
        """Создание таблиц channels_meta и discovery_actions."""
        with self.db._pool.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS channels_meta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER REFERENCES channels(id),
                    category TEXT,
                    author_type TEXT,
                    subscribers INTEGER,
                    avg_views INTEGER,
                    scoring INTEGER,
                    subscribed_at TIMESTAMP,
                    last_post_date TIMESTAMP,
                    topic_relevance_pct REAL,
                    status TEXT DEFAULT 'active',
                    status_changed_at TIMESTAMP,
                    source_channel TEXT,
                    UNIQUE(channel_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovery_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT,
                    channel_username TEXT,
                    profile TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    # ── Подключение / отключение ──────────────────────────────────────

    async def start(self):
        session_name = self.config.get("telegram.session_name", "session")
        await safe_connect(self.client, session_name)
        logger.info(f"ChannelDiscovery подключен (профиль: {self.profile})")

    async def stop(self):
        await self.client.disconnect()
        self.db.close()

    # ── Вспомогательные методы БД ─────────────────────────────────────

    def _count_today_actions(self, action_type: str) -> int:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db._pool.get_connection() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM discovery_actions "
                "WHERE action_type=? AND profile=? AND created_at>=?",
                (action_type, self.profile, today_start),
            )
            return cur.fetchone()[0]

    def _log_action(self, action_type: str, channel_username: str):
        with self.db._pool.get_connection() as conn:
            conn.execute(
                "INSERT INTO discovery_actions "
                "(action_type, channel_username, profile, created_at) VALUES (?,?,?,?)",
                (action_type, channel_username, self.profile, datetime.now(UTC)),
            )

    def _get_known_usernames(self) -> set[str]:
        """Юзернеймы каналов, которые мы уже проверяли (channels_meta)."""
        with self.db._pool.get_connection() as conn:
            rows = conn.execute(
                "SELECT c.username FROM channels_meta cm "
                "JOIN channels c ON c.id = cm.channel_id "
                "WHERE cm.category = ?",
                (self.profile,),
            ).fetchall()
            return {r[0].lower() for r in rows}

    # ══════════════════════════════════════════════════════════════════
    #  1. ПОИСК ЧЕРЕЗ РЕКОМЕНДАЦИИ
    # ══════════════════════════════════════════════════════════════════

    async def discover_via_recommendations(self) -> list[dict]:
        """
        Для каждого подписанного канала берём рекомендации Telegram.
        Фильтруем уже подписанных и ранее проверенных.
        """
        seed_channels = self.db.get_active_channels()
        existing = {ch["username"].lower() for ch in seed_channels}
        known = self._get_known_usernames()
        skip = existing | known

        logger.info(
            f"Поиск рекомендаций: {len(seed_channels)} каналов, "
            f"пропускаем {len(skip)} известных"
        )

        candidates: dict[str, dict] = {}

        for i, ch in enumerate(seed_channels):
            username = ch["username"]
            try:
                entity = await self.client.get_entity(username)
                if not isinstance(entity, Channel):
                    continue

                result = await self.client(
                    GetChannelRecommendationsRequest(channel=entity)
                )

                for chat in result.chats:
                    if not isinstance(chat, Channel) or chat.megagroup:
                        continue
                    rec_username = chat.username
                    if not rec_username:
                        continue
                    if rec_username.lower() in skip:
                        continue
                    if rec_username not in candidates:
                        candidates[rec_username] = {
                            "username": rec_username,
                            "title": chat.title or "",
                            "telegram_id": chat.id,
                            "source": f"rec:{username}",
                        }

                if (i + 1) % 20 == 0:
                    logger.info(f"  Обработано {i+1}/{len(seed_channels)} каналов, "
                                f"найдено {len(candidates)} кандидатов")

                await asyncio.sleep(random.uniform(API_DELAY_MIN, API_DELAY_MAX))

            except FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}s при рекомендациях @{username}, прерываем сбор")
                break  # прерываем сбор рекомендаций, работаем с тем что есть
            except (ChannelPrivateError, ChatAdminRequiredError):
                continue
            except Exception as e:
                logger.error(f"Ошибка рекомендаций @{username}: {e}")

        logger.info(f"Найдено {len(candidates)} новых кандидатов")
        return list(candidates.values())

    # ══════════════════════════════════════════════════════════════════
    #  2. ВАЛИДАЦИЯ ЧЕРЕЗ GEMINI
    # ══════════════════════════════════════════════════════════════════

    async def _gemini_check(self, prompt: str) -> bool:
        """Отправить промпт в Gemini, вернуть True если ответ начинается с 'Да'."""
        try:
            response = await asyncio.to_thread(
                self._gemini_model.generate_content, prompt,
            )
            answer = (response.text or "").strip().lower()
            return answer.startswith("да")
        except Exception as e:
            logger.warning(f"Gemini ошибка: {e}")
            return False

    async def _fetch_channel_web(self, username: str) -> dict | None:
        """
        Получить посты и метаданные канала через t.me/s/username (без API).
        Возвращает {posts: list[str], dates: list[datetime], subscribers: int} или None.
        """
        url = f"https://t.me/s/{username}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.debug(f"  @{username} — t.me вернул {resp.status}")
                        return None
                    html = await resp.text()
        except Exception as e:
            logger.warning(f"  @{username} — ошибка загрузки t.me: {e}")
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Посты
        post_divs = soup.select(".tgme_widget_message_text")
        posts = []
        for div in post_divs:
            text = div.get_text(separator="\n", strip=True)
            if text:
                posts.append(text)

        # Даты
        dates = []
        for time_tag in soup.select("time[datetime]"):
            try:
                dt = datetime.fromisoformat(time_tag["datetime"])
                dates.append(dt)
            except (ValueError, KeyError):
                pass

        # Подписчики
        subscribers = 0
        extra_div = soup.select_one(".tgme_channel_info_counter .counter_value")
        if extra_div:
            raw = extra_div.get_text(strip=True).replace(" ", "").replace("\xa0", "")
            # "2.75K" → 2750, "1.2M" → 1200000
            m = re.match(r"([\d.]+)([KkМмMm]?)", raw)
            if m:
                val = float(m.group(1))
                suffix = m.group(2).upper()
                if suffix in ("K", "К"):
                    val *= 1000
                elif suffix in ("M", "М"):
                    val *= 1_000_000
                subscribers = int(val)

        if not posts:
            return None

        return {"posts": posts, "dates": dates, "subscribers": subscribers}

    async def _validate_candidate(self, candidate: dict) -> bool:
        """
        Двухэтапная проверка кандидата (0 Telegram API вызовов):
        1) Quick check — название → Gemini
        2) Deep check — посты с t.me/s/ → Gemini
        """
        username = candidate["username"]
        try:
            # ── Quick check (только название) ─────────────────────────
            quick_prompt = self.prompts["quick"].format(title=candidate["title"])
            if not await self._gemini_check(quick_prompt):
                logger.info(f"  @{username} — quick check: НЕТ")
                return False
            logger.info(f"  @{username} — quick check: ДА")

            # ── Загрузка через веб (0 Telegram API) ──────────────────
            web_data = await self._fetch_channel_web(username)
            if not web_data:
                logger.info(f"  @{username} — не удалось загрузить с t.me")
                return False

            # Alive check
            if web_data["dates"]:
                latest = max(web_data["dates"])
                days_since = (datetime.now(UTC) - latest.replace(tzinfo=UTC)).days
                if days_since > CHANNEL_ALIVE_DAYS:
                    logger.info(f"  @{username} — последний пост {days_since}д назад")
                    return False
                candidate["last_post_date"] = latest.isoformat()
            else:
                logger.info(f"  @{username} — нет дат постов")
                return False

            candidate["subscribers"] = web_data["subscribers"]

            # ── Deep check (посты → Gemini) ───────────────────────────
            posts_text = "\n---\n".join(web_data["posts"][:DEEP_CHECK_POSTS])
            if len(posts_text) > MAX_POSTS_TEXT_LEN:
                posts_text = posts_text[:MAX_POSTS_TEXT_LEN] + "…"

            deep_prompt = self.prompts["deep"].format(
                title=candidate["title"], posts=posts_text,
            )
            if not await self._gemini_check(deep_prompt):
                logger.info(f"  @{username} — deep check: НЕТ")
                return False

            subs = candidate["subscribers"]
            logger.info(f"  @{username} — deep check: ДА ({subs} подписчиков)")
            candidate["scoring"] = 100
            candidate["topic_relevance_pct"] = 100.0
            return True

        except Exception as e:
            logger.error(f"Ошибка валидации @{username}: {e}")
            return False

    # ══════════════════════════════════════════════════════════════════
    #  3. ПОДПИСКА
    # ══════════════════════════════════════════════════════════════════

    async def subscribe_to_channels(self, candidates: list[dict]) -> list[dict]:
        """Подписка с антифлудом."""
        already_today = self._count_today_actions("subscribe")
        remaining = MAX_SUBSCRIPTIONS_PER_DAY - already_today

        if remaining <= 0:
            logger.info(
                f"Лимит подписок исчерпан ({already_today}/{MAX_SUBSCRIPTIONS_PER_DAY})"
            )
            return []

        top = candidates[:remaining]
        subscribed = []

        for i, candidate in enumerate(top):
            username = candidate["username"]
            try:
                logger.info(f"Подписка [{i+1}/{len(top)}] @{username}")

                entity = await self.client.get_entity(username)
                await self.client(JoinChannelRequest(entity))

                channel_id = self.db.add_channel(username, candidate.get("title", ""))
                self._save_channel_meta(channel_id, candidate)
                self._log_action("subscribe", username)

                subscribed.append(candidate)
                logger.info(f"Подписан на @{username}")

                if i < len(top) - 1:
                    delay = random.uniform(SUBSCRIBE_DELAY_MIN, SUBSCRIBE_DELAY_MAX)
                    logger.info(f"Задержка {delay:.0f}с...")
                    await asyncio.sleep(delay)

            except FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}s, прерываем подписки")
                break
            except (ChannelPrivateError, ChatAdminRequiredError) as e:
                logger.warning(f"Не удалось подписаться на @{username}: {e}")
            except Exception as e:
                logger.error(f"Ошибка подписки на @{username}: {e}")

        logger.info(f"Подписано {len(subscribed)}/{len(top)}")
        return subscribed

    def _save_channel_meta(self, channel_id: int, candidate: dict):
        with self.db._pool.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO channels_meta
                (channel_id, category, subscribers, avg_views, scoring,
                 subscribed_at, last_post_date, topic_relevance_pct,
                 status, source_channel)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """, (
                channel_id, self.profile,
                candidate.get("subscribers", 0),
                candidate.get("avg_views", 0),
                candidate.get("scoring", 0),
                datetime.now(UTC).isoformat(),
                candidate.get("last_post_date"),
                candidate.get("topic_relevance_pct", 0),
                candidate.get("source", ""),
            ))

    # ══════════════════════════════════════════════════════════════════
    #  4. ПРОВЕРКА АКТУАЛЬНОСТИ
    # ══════════════════════════════════════════════════════════════════

    async def check_actuality(self):
        """Помечает неактивные каналы (нет постов > 14 дней). Через t.me/s/ без API."""
        with self.db._pool.get_connection() as conn:
            rows = conn.execute("""
                SELECT cm.id, cm.channel_id, c.username
                FROM channels_meta cm
                JOIN channels c ON c.id = cm.channel_id
                WHERE cm.category = ? AND cm.status = 'active'
            """, (self.profile,)).fetchall()

        if not rows:
            return

        logger.info(f"Проверка актуальности {len(rows)} каналов")
        updated = 0

        for meta_id, channel_id, username in rows:
            try:
                web_data = await self._fetch_channel_web(username)

                if not web_data or not web_data["dates"]:
                    self._update_status(meta_id, "inactive")
                    updated += 1
                    continue

                latest = max(web_data["dates"])
                days_since = (datetime.now(UTC) - latest.replace(tzinfo=UTC)).days

                if days_since > CHANNEL_ALIVE_DAYS:
                    self._update_status(meta_id, "inactive")
                    updated += 1

                await asyncio.sleep(random.uniform(0.5, 1.5))

            except Exception as e:
                logger.warning(f"Ошибка проверки @{username}: {e}")

        logger.info(f"Обновлено статусов: {updated}")

    def _update_status(self, meta_id: int, status: str):
        with self.db._pool.get_connection() as conn:
            conn.execute(
                "UPDATE channels_meta SET status=?, status_changed_at=? WHERE id=?",
                (status, datetime.now(UTC).isoformat(), meta_id),
            )
        logger.info(f"Канал meta_id={meta_id} -> {status}")

    # ══════════════════════════════════════════════════════════════════
    #  5. ОТПИСКА
    # ══════════════════════════════════════════════════════════════════

    async def unsubscribe_inactive(self, limit: int = 5) -> list[str]:
        already_today = self._count_today_actions("unsubscribe")
        remaining = min(limit, MAX_UNSUBSCRIPTIONS_PER_DAY - already_today)

        if remaining <= 0:
            logger.info("Лимит отписок исчерпан")
            return []

        with self.db._pool.get_connection() as conn:
            rows = conn.execute("""
                SELECT cm.id, cm.channel_id, c.username
                FROM channels_meta cm
                JOIN channels c ON c.id = cm.channel_id
                WHERE cm.category = ? AND cm.status IN ('inactive', 'topic_changed')
                ORDER BY cm.status_changed_at ASC
                LIMIT ?
            """, (self.profile, remaining)).fetchall()

        unsubscribed = []
        for meta_id, channel_id, username in rows:
            try:
                entity = await self.client.get_entity(username)
                await self.client(LeaveChannelRequest(entity))

                with self.db._pool.get_connection() as conn:
                    conn.execute(
                        "UPDATE channels SET is_active=0 WHERE id=?", (channel_id,),
                    )
                    conn.execute(
                        "UPDATE channels_meta SET status='unsubscribed' WHERE id=?",
                        (meta_id,),
                    )

                self._log_action("unsubscribe", username)
                unsubscribed.append(username)
                logger.info(f"Отписан от @{username}")

                if len(unsubscribed) < len(rows):
                    await asyncio.sleep(random.uniform(30, 60))

            except Exception as e:
                logger.error(f"Ошибка отписки от @{username}: {e}")

        logger.info(f"Отписано от {len(unsubscribed)} каналов")
        return unsubscribed

    # ══════════════════════════════════════════════════════════════════
    #  6. ПОЛНЫЙ ЦИКЛ
    # ══════════════════════════════════════════════════════════════════

    async def run_full_cycle(self):
        """Рекомендации -> валидация -> подписка -> проверка -> отписка."""
        logger.info(f"Полный цикл discovery для '{self.profile}'")

        # 1. Рекомендации
        candidates = await self.discover_via_recommendations()

        if candidates:
            # 2. Валидация через Gemini (берём случайную выборку чтобы не словить FloodWait)
            if len(candidates) > MAX_CANDIDATES_PER_RUN:
                random.shuffle(candidates)
                candidates = candidates[:MAX_CANDIDATES_PER_RUN]
                logger.info(f"Отобрано {MAX_CANDIDATES_PER_RUN} случайных кандидатов для валидации")
            logger.info(f"Валидация {len(candidates)} кандидатов...")
            validated = []
            for i, c in enumerate(candidates):
                logger.info(f"[{i+1}/{len(candidates)}] @{c['username']}...")
                if await self._validate_candidate(c):
                    validated.append(c)
                await asyncio.sleep(random.uniform(1, 3))  # пауза между Gemini-запросами

            # 3. Подписка
            if validated:
                logger.info(f"Прошли валидацию: {len(validated)} каналов")
                await self.subscribe_to_channels(validated)
            else:
                logger.info("Ни один кандидат не прошёл валидацию")
        else:
            logger.info("Новых кандидатов не найдено")

        # 4. Проверка актуальности
        await self.check_actuality()

        # 5. Отписка
        await self.unsubscribe_inactive()

        logger.info(f"Цикл discovery завершён для '{self.profile}'")

    # ══════════════════════════════════════════════════════════════════
    #  7. СТАТИСТИКА
    # ══════════════════════════════════════════════════════════════════

    def get_discovery_stats(self) -> dict:
        with self.db._pool.get_connection() as conn:
            stats = {}

            cur = conn.execute(
                "SELECT COUNT(*) FROM channels_meta "
                "WHERE category=? AND status='active'",
                (self.profile,),
            )
            stats["active_discovered"] = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COUNT(*) FROM channels_meta WHERE category=?",
                (self.profile,),
            )
            stats["total_discovered"] = cur.fetchone()[0]

            today_start = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            cur = conn.execute(
                "SELECT COUNT(*) FROM discovery_actions "
                "WHERE action_type='subscribe' AND profile=? AND created_at>=?",
                (self.profile, today_start),
            )
            stats["subscribed_today"] = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COUNT(*) FROM discovery_actions "
                "WHERE action_type='unsubscribe' AND profile=? AND created_at>=?",
                (self.profile, today_start),
            )
            stats["unsubscribed_today"] = cur.fetchone()[0]

            cur = conn.execute("""
                SELECT c.username, cm.subscribers
                FROM channels_meta cm JOIN channels c ON c.id = cm.channel_id
                WHERE cm.category=? AND cm.status='active'
                ORDER BY cm.subscribers DESC LIMIT 5
            """, (self.profile,))
            stats["top_channels"] = [
                {"username": r[0], "subscribers": r[1]}
                for r in cur.fetchall()
            ]

            return stats
