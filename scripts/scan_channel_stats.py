#!/usr/bin/env python3
"""
Адаптивный сканер статистики каналов с самообучением.

Ключевая идея: Telegram считает СУММАРНЫЙ дневной лимит запросов на сессию,
а не лимит за пачку. Поэтому нужно отслеживать не только параметры пачки,
но и на каком СУММАРНОМ канале за день случился FloodWait.

Алгоритм самообучения:
  - Каждый FloodWait записывается с контекстом: суммарный канал за день,
    номер пачки, размер пачки, задержка, время суток
  - Из истории вычисляется "безопасный дневной лимит" (safe_daily_limit)
  - Параметры пачки подбираются так чтобы не превысить этот лимит за день
  - После успешных прогонов лимит осторожно увеличивается
  - Entity кэшируется на диск — повторные запуски не делают ResolveUsernameRequest

Использование:
    python scripts/scan_channel_stats.py --profile marketplace
    python scripts/scan_channel_stats.py --profile ai
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import InputChannel

from database.db import Database
from utils.config import load_config
from utils.logger import setup_logger, configure_logging
from utils.telegram_helpers import safe_connect

logger = setup_logger(__name__)

LEARNING_DIR = Path(__file__).parent.parent / "data" / "scan_learning"

# Абсолютные границы параметров
MIN_BATCH_SIZE    = 3
MAX_BATCH_SIZE    = 50
MIN_BATCH_PAUSE   = 120    # 2 мин
MAX_BATCH_PAUSE   = 7200   # 2 часа
MIN_CHANNEL_DELAY = 15
MAX_CHANNEL_DELAY = 180
MIN_DAILY_LIMIT   = 10     # меньше не имеет смысла
MAX_DAILY_LIMIT   = 500    # потолок


# ════════════════════════════════════════════════════════════════════════════════
# ScanKnowledge — мозг сканера
# ════════════════════════════════════════════════════════════════════════════════

class ScanKnowledge:
    """
    Персистентная память сканера. Хранит историю FloodWait и учится на ней.

    Главная метрика: safe_daily_limit — сколько каналов можно просканировать
    за день без блокировки. Вычисляется из истории:
      - Если флуд случился на канале N — значит лимит < N
      - safe_daily_limit = min(все N где был флуд) * safety_factor
      - После успешных полных прогонов — осторожно поднимаем

    Из safe_daily_limit автоматически вычисляются batch_size и batch_pause:
      - Разбиваем день (86400с) на равные окна
      - batch_size = safe_daily_limit / num_batches_per_day
      - batch_pause = 86400 / num_batches_per_day - batch_size * channel_delay
    """

    def __init__(self, profile: str):
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LEARNING_DIR / f"{profile}.json"
        self.profile = profile
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
        else:
            data = {}

        # Главный параметр — безопасный дневной лимит
        self.safe_daily_limit = data.get("safe_daily_limit", 80)
        self.channel_delay    = data.get("channel_delay", 45.0)

        # История событий
        self.flood_history    = data.get("flood_history", [])    # FloodWait события
        self.run_history      = data.get("run_history", [])      # завершённые прогоны
        self.success_runs     = data.get("success_runs", 0)      # подряд успешных прогонов
        self.total_floods     = data.get("total_floods", 0)

        # Вычисляем параметры пачек из safe_daily_limit
        self._recalc_batch_params()

    def _recalc_batch_params(self):
        """
        Из safe_daily_limit вычисляем batch_size и batch_pause.
        Логика: делим день на окна, в каждом окне — одна пачка.
        Пачка не должна занимать больше 30% окна (остальное — пауза).
        """
        # Сколько пачек в день нам нужно чтобы покрыть safe_daily_limit
        # при разумном batch_size
        target_batch = max(MIN_BATCH_SIZE, min(20, self.safe_daily_limit // 5))
        num_batches = max(1, (self.safe_daily_limit + target_batch - 1) // target_batch)

        # Время окна для одной пачки
        window_s = 86400 // num_batches

        # Время на саму пачку (каналы * задержка)
        scan_time = target_batch * self.channel_delay

        # Пауза = окно - время сканирования, но минимум MIN_BATCH_PAUSE
        pause = max(MIN_BATCH_PAUSE, int(window_s - scan_time))
        pause = min(MAX_BATCH_PAUSE, pause)

        self.batch_size  = target_batch
        self.batch_pause = pause

    def save(self):
        data = {
            "safe_daily_limit": self.safe_daily_limit,
            "channel_delay":    round(self.channel_delay, 1),
            "batch_size":       self.batch_size,
            "batch_pause":      self.batch_pause,
            "flood_history":    self.flood_history[-100:],
            "run_history":      self.run_history[-30:],
            "success_runs":     self.success_runs,
            "total_floods":     self.total_floods,
            "updated_at":       datetime.utcnow().isoformat(),
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ── Главный метод обучения ────────────────────────────────────────────────

    def on_flood(
        self,
        wait_seconds: int,
        *,
        total_scanned_today: int,   # СКОЛЬКО каналов уже просканировали сегодня до флуда
        batch_num: int,             # номер пачки (1, 2, 3...)
        batch_size: int,            # размер пачки в момент флуда
        channel_in_batch: int,      # на каком канале внутри пачки случился флуд
        channel_delay: float,
    ):
        """
        Главный метод обучения. Получает полный контекст FloodWait.

        total_scanned_today — это ключевая метрика:
        флуд случился ПОСЛЕ того как мы просканировали total_scanned_today каналов.
        Значит реальный лимит сессии < total_scanned_today.
        """
        self.total_floods += 1
        self.success_runs = 0  # сбрасываем счётчик успешных прогонов

        # Суммарный канал за день где случился флуд
        flood_at_channel = total_scanned_today + channel_in_batch

        event = {
            "ts":                datetime.utcnow().isoformat(),
            "wait_s":            wait_seconds,
            "flood_at_channel":  flood_at_channel,   # ← главная метрика
            "batch_num":         batch_num,
            "batch_size":        batch_size,
            "channel_in_batch":  channel_in_batch,
            "channel_delay":     round(channel_delay, 1),
            "old_daily_limit":   self.safe_daily_limit,
        }
        self.flood_history.append(event)

        # ── Урок 1: обновляем safe_daily_limit ───────────────────────────
        old_limit = self.safe_daily_limit

        # Собираем все известные "точки флуда" из истории
        flood_points = [e["flood_at_channel"] for e in self.flood_history
                        if "flood_at_channel" in e]

        if flood_points:
            # Минимальная точка флуда — это верхняя граница лимита
            min_flood_point = min(flood_points)

            # safety_factor зависит от тяжести флуда:
            # тяжёлый флуд → берём 50% от точки флуда
            # лёгкий → 70%
            if wait_seconds > 3600:
                safety_factor = 0.50
            elif wait_seconds > 300:
                safety_factor = 0.60
            else:
                safety_factor = 0.70

            new_limit = max(MIN_DAILY_LIMIT, int(min_flood_point * safety_factor))
            # Лимит может только уменьшаться при флуде, никогда не расти
            self.safe_daily_limit = min(self.safe_daily_limit, new_limit)
        else:
            # Первый флуд — просто снижаем текущий лимит
            if wait_seconds > 3600:
                self.safe_daily_limit = max(MIN_DAILY_LIMIT, int(self.safe_daily_limit * 0.5))
            elif wait_seconds > 300:
                self.safe_daily_limit = max(MIN_DAILY_LIMIT, int(self.safe_daily_limit * 0.6))
            else:
                self.safe_daily_limit = max(MIN_DAILY_LIMIT, int(self.safe_daily_limit * 0.75))

        # ── Урок 2: обновляем channel_delay ──────────────────────────────
        if wait_seconds > 3600:
            self.channel_delay = min(MAX_CHANNEL_DELAY, self.channel_delay * 1.5)
        elif wait_seconds > 300:
            self.channel_delay = min(MAX_CHANNEL_DELAY, self.channel_delay * 1.3)
        else:
            self.channel_delay = min(MAX_CHANNEL_DELAY, self.channel_delay * 1.1)

        # Пересчитываем параметры пачек
        self._recalc_batch_params()

        severity = "🔴 жёсткий (>1ч)" if wait_seconds > 3600 else \
                   "🟡 серьёзный (>5мин)" if wait_seconds > 300 else \
                   "🟢 лёгкий (<5мин)"

        logger.warning(
            "🧠 Урок #%d [%s] FloodWait=%ds на канале %d за день\n"
            "   safe_daily_limit: %d → %d | delay: %.0fs → %.0fs\n"
            "   Новые параметры: batch=%d, pause=%ds (%dмин)",
            self.total_floods, severity, wait_seconds, flood_at_channel,
            old_limit, self.safe_daily_limit,
            channel_delay, self.channel_delay,
            self.batch_size, self.batch_pause, self.batch_pause // 60,
        )
        self.save()

    def on_run_complete(self, total_scanned: int, total_channels: int, had_flood: bool):
        """
        Вызывается по завершении полного прогона.
        Если прогон прошёл без флуда — осторожно увеличиваем лимит.
        """
        event = {
            "ts":            datetime.utcnow().isoformat(),
            "total_scanned": total_scanned,
            "total_channels": total_channels,
            "had_flood":     had_flood,
            "daily_limit":   self.safe_daily_limit,
        }
        self.run_history.append(event)

        if not had_flood and total_scanned >= total_channels:
            # Полный успешный прогон без флуда
            self.success_runs += 1

            # После 2 успешных прогонов подряд — поднимаем лимит на 10%
            if self.success_runs >= 2:
                old = self.safe_daily_limit
                self.safe_daily_limit = min(
                    MAX_DAILY_LIMIT,
                    int(self.safe_daily_limit * 1.10)
                )
                self.channel_delay = max(
                    MIN_CHANNEL_DELAY,
                    self.channel_delay * 0.95
                )
                self._recalc_batch_params()

                if self.safe_daily_limit != old:
                    logger.info(
                        "🧠 Оптимизация (%d успешных прогонов): "
                        "daily_limit %d→%d, delay %.0fs→%.0fs, batch=%d, pause=%ds",
                        self.success_runs, old, self.safe_daily_limit,
                        self.channel_delay / 0.95, self.channel_delay,
                        self.batch_size, self.batch_pause,
                    )
        else:
            self.success_runs = 0

        self.save()

    def summary(self) -> str:
        """Краткая сводка текущих параметров."""
        return (
            f"daily_limit={self.safe_daily_limit} | "
            f"batch={self.batch_size} каналов | "
            f"pause={self.batch_pause}с ({self.batch_pause//60}мин) | "
            f"delay={self.channel_delay:.0f}с | "
            f"флудов всего: {self.total_floods} | "
            f"успешных прогонов подряд: {self.success_runs}"
        )

    def flood_analysis(self) -> str:
        """Аналитика по истории флудов для отладки."""
        if not self.flood_history:
            return "История флудов пуста"
        points = [e["flood_at_channel"] for e in self.flood_history if "flood_at_channel" in e]
        if not points:
            return "Нет данных о точках флуда"
        return (
            f"Точки флуда: min={min(points)}, max={max(points)}, "
            f"avg={sum(points)//len(points)} | "
            f"Последние: {points[-5:]}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# EntityCache — кэш TG entity
# ════════════════════════════════════════════════════════════════════════════════

class EntityCache:
    """
    Кэширует channel_id + access_hash чтобы не делать ResolveUsernameRequest.
    Это главный способ снизить количество запросов к TG API.
    """

    def __init__(self, profile: str):
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LEARNING_DIR / f"{profile}_entity_cache.json"
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text())
            except Exception:
                self._cache = {}

    def save(self):
        self.path.write_text(json.dumps(self._cache, indent=2))

    def get(self, username: str) -> InputChannel | None:
        entry = self._cache.get(username.lower())
        if entry:
            return InputChannel(entry["channel_id"], entry["access_hash"])
        return None

    def put(self, username: str, entity):
        try:
            self._cache[username.lower()] = {
                "channel_id":  entity.id,
                "access_hash": entity.access_hash,
                "title":       getattr(entity, "title", ""),
                "cached_at":   datetime.utcnow().isoformat(),
            }
        except AttributeError:
            pass


# ════════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ════════════════════════════════════════════════════════════════════════════════

def extract_contacts(text: str) -> str:
    if not text:
        return ""
    found = set()
    found.update(re.findall(r"@[\w]{3,}", text))
    found.update(re.findall(r"https?://[^\s]+", text))
    found.update(re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text))
    return ", ".join(sorted(found))


async def ensure_connected(client: TelegramClient, session_name: str) -> None:
    if not client.is_connected():
        logger.info("  🔄 Переподключение к Telegram...")
        await safe_connect(client, session_name)


def get_already_scanned_today(db: Database) -> set[int]:
    cutoff = datetime.utcnow() - timedelta(hours=25)
    with db._pool.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT channel_id FROM channel_stats WHERE scanned_at >= ?",
            (cutoff,),
        ).fetchall()
    return {row[0] for row in rows}


# ════════════════════════════════════════════════════════════════════════════════
# Сканирование одного канала
# ════════════════════════════════════════════════════════════════════════════════

class FloodSignal(Exception):
    """Внутренний сигнал: поймали FloodWait, нужно обработать наверху."""
    def __init__(self, seconds: int):
        self.seconds = seconds


async def scan_one(
    client: TelegramClient,
    session_name: str,
    db: Database,
    channel: dict,
    delay: float,
    entity_cache: EntityCache,
) -> bool:
    """
    Сканировать один канал.
    Возвращает True если обработан, False если нужен повтор (разрыв соединения).
    Бросает FloodSignal если поймали FloodWait.
    """
    username = channel["username"]
    channel_id = channel["id"]

    await ensure_connected(client, session_name)

    # Берём entity из кэша если есть — экономим ResolveUsernameRequest
    cached = entity_cache.get(username)
    if cached:
        try:
            entity = await client.get_entity(cached)
        except Exception:
            entity_cache._cache.pop(username.lower(), None)
            entity = await client.get_entity(username)
    else:
        entity = await client.get_entity(username)

    entity_cache.put(username, entity)

    full = await client(GetFullChannelRequest(entity))
    fc = full.full_chat

    participants = getattr(fc, "participants_count", 0) or 0
    about = getattr(fc, "about", "") or ""
    contacts = extract_contacts(about)

    views_list = []
    async for msg in client.iter_messages(entity, limit=20):
        if msg.views:
            views_list.append(msg.views)
        with db._pool.get_connection() as conn:
            conn.execute(
                "UPDATE raw_messages SET views=?, forwards=? WHERE channel_id=? AND message_id=?",
                (msg.views or 0, msg.forwards or 0, channel_id, msg.id),
            )
    avg_views = int(sum(views_list) / len(views_list)) if views_list else 0

    db.update_channel_stats(channel_id, participants, avg_views, about, contacts)
    logger.info(
        "  ✅ @%-30s  %7d подп.  avg %5d просм.%s",
        username, participants, avg_views,
        f"  📬 {contacts}" if contacts else "",
    )
    await asyncio.sleep(delay)
    return True


async def scan_channel_safe(
    client: TelegramClient,
    session_name: str,
    db: Database,
    channel: dict,
    delay: float,
    entity_cache: EntityCache,
) -> bool:
    """
    Обёртка с обработкой исключений.
    Бросает FloodSignal при FloodWait.
    Возвращает True/False (done/retry).
    """
    try:
        return await scan_one(client, session_name, db, channel, delay, entity_cache)

    except FloodWaitError as e:
        raise FloodSignal(e.seconds)

    except (ChannelPrivateError, ChatAdminRequiredError):
        logger.debug("  ⚠️  @%s недоступен", channel["username"])
        await asyncio.sleep(min(delay, 10))
        return True

    except Exception as e:
        err = str(e)
        if "disconnected" in err.lower():
            logger.warning("  🔌 @%s: разрыв соединения, переподключение...", channel["username"])
            try:
                await safe_connect(client, session_name)
            except Exception as ce:
                logger.error("  Переподключение не удалось: %s", ce)
                await asyncio.sleep(10)
            return False  # повторить
        logger.warning("  ❌ @%s: %s", channel["username"], e)
        await asyncio.sleep(min(delay, 10))
        return True


# ════════════════════════════════════════════════════════════════════════════════
# Главный цикл
# ════════════════════════════════════════════════════════════════════════════════

async def main(profile: str):
    config = load_config(profile=profile)
    configure_logging(
        level=config.log_level,
        log_file=config.log_file,
        rotation=config.log_rotation,
        file_format=config.log_format,
        date_format=config.log_date_format,
    )

    knowledge = ScanKnowledge(profile)
    entity_cache = EntityCache(profile)

    db = Database(config.db_path, **config.database_settings())
    all_channels = db.get_active_channels()
    total = len(all_channels)

    if total == 0:
        logger.error("Нет активных каналов в профиле %s", profile)
        sys.exit(1)

    already_done = get_already_scanned_today(db)
    channels_todo = [ch for ch in all_channels if ch["id"] not in already_done]
    skipped_resume = total - len(channels_todo)

    logger.info("=" * 72)
    logger.info("📡 АДАПТИВНЫЙ СКАНЕР — профиль: %s", profile)
    logger.info("   Всего каналов: %d  |  К сканированию: %d  |  Уже готово: %d",
                total, len(channels_todo), skipped_resume)
    logger.info("   🧠 %s", knowledge.summary())
    logger.info("   📊 %s", knowledge.flood_analysis())
    logger.info("   📦 Entity в кэше: %d", len(entity_cache._cache))
    logger.info("=" * 72)

    if not channels_todo:
        logger.info("✅ Все каналы уже просканированы.")
        db.close()
        return

    # Сессия (отдельная от listener)
    base_session = config.get("telegram.session_name", "")
    if base_session.endswith("/session"):
        session_name = base_session[:-8] + "/processor"
    elif base_session.endswith("/session.session"):
        session_name = base_session[:-16] + "/processor"
    else:
        session_name = base_session + "_processor"

    client = TelegramClient(
        session_name,
        config.telegram_api_id,
        config.telegram_api_hash,
        flood_sleep_threshold=60,  # FloodWait > 60с — бросаем исключение, не спим сами
    )

    had_flood_this_run = False

    try:
        await safe_connect(client, session_name)

        remaining = list(channels_todo)
        scanned_today = skipped_resume   # сколько уже просканировали за день (включая resume)
        scanned_this_run = 0
        with_contacts = 0
        batch_num = 0

        while remaining:
            batch_num += 1
            batch = remaining[:knowledge.batch_size]

            logger.info(
                "── Пачка #%d: %d каналов | delay=%.0fс | пауза после=%ds (%dмин) "
                "| всего за день: %d/%d ──",
                batch_num, len(batch),
                knowledge.channel_delay,
                knowledge.batch_pause, knowledge.batch_pause // 60,
                scanned_today, knowledge.safe_daily_limit,
            )

            batch_scanned = 0
            flood_in_batch = False

            for ch_in_batch, channel in enumerate(batch, start=1):
                idx_global = skipped_resume + scanned_this_run + 1
                logger.info("[%d/%d] @%s  (день: %d/%d)",
                            idx_global, total, channel["username"],
                            scanned_today + 1, knowledge.safe_daily_limit)

                # Повторяем при разрыве соединения
                while True:
                    try:
                        done = await scan_channel_safe(
                            client, session_name, db, channel,
                            knowledge.channel_delay, entity_cache,
                        )
                    except FloodSignal as fs:
                        # ── Поймали FloodWait ─────────────────────────────
                        had_flood_this_run = True
                        flood_in_batch = True

                        knowledge.on_flood(
                            fs.seconds,
                            total_scanned_today=scanned_today,  # ← суммарный за день
                            batch_num=batch_num,
                            batch_size=len(batch),
                            channel_in_batch=ch_in_batch,       # ← позиция внутри пачки
                            channel_delay=knowledge.channel_delay,
                        )

                        wait = fs.seconds + 10
                        logger.warning(
                            "  ⏳ FloodWait %ds для @%s — жду %ds...",
                            fs.seconds, channel["username"], wait,
                        )
                        await asyncio.sleep(wait)
                        break  # прерываем пачку, идём на паузу

                    if not done:
                        continue  # повторить канал (разрыв соединения)

                    # Успешно
                    remaining.pop(0)
                    batch_scanned += 1
                    scanned_today += 1
                    scanned_this_run += 1

                    try:
                        with db._pool.get_connection() as conn:
                            row = conn.execute(
                                "SELECT contact_info FROM channel_stats "
                                "WHERE channel_id=? ORDER BY scanned_at DESC LIMIT 1",
                                (channel["id"],),
                            ).fetchone()
                        if row and row[0]:
                            with_contacts += 1
                    except Exception:
                        pass
                    break  # следующий канал в пачке

                if flood_in_batch:
                    break  # прерываем for-loop пачки

            # ── Сохраняем кэш после каждой пачки ─────────────────────────
            entity_cache.save()

            # ── Пауза между пачками ───────────────────────────────────────
            if not remaining:
                break

            if flood_in_batch:
                # После флуда: уже ждали flood_wait, теперь ещё batch_pause
                extra = knowledge.batch_pause
                logger.info(
                    "⏸  Пауза после FloodWait: %ds (%dмин) | 🧠 %s",
                    extra, extra // 60, knowledge.summary(),
                )
                await asyncio.sleep(extra)
            else:
                # Успешная пачка
                pause = knowledge.batch_pause
                logger.info(
                    "⏸  Пауза между пачками: %ds (%dмин) | "
                    "день: %d/%d просканировано | 🧠 %s",
                    pause, pause // 60,
                    scanned_today, knowledge.safe_daily_limit,
                    knowledge.summary(),
                )
                await asyncio.sleep(pause)

        # ── Финал ────────────────────────────────────────────────────────
        entity_cache.save()
        knowledge.on_run_complete(scanned_this_run, len(channels_todo), had_flood_this_run)

        logger.info("=" * 72)
        logger.info("✅ Готово: %d новых + %d из кэша | контакты: %d каналов",
                    scanned_this_run, skipped_resume, with_contacts)
        logger.info("🧠 Итог: %s", knowledge.summary())
        logger.info("📊 %s", knowledge.flood_analysis())

        # Топ-10
        try:
            with db._pool.get_connection() as conn:
                rows = conn.execute(
                    """SELECT c.username, cs.participants_count, cs.avg_message_views
                       FROM channel_stats cs JOIN channels c ON cs.channel_id = c.id
                       WHERE cs.id IN (SELECT MAX(id) FROM channel_stats GROUP BY channel_id)
                       ORDER BY cs.participants_count DESC LIMIT 10"""
                ).fetchall()
            logger.info("=" * 72)
            logger.info("📊 ТОП-10 по подписчикам:")
            for i, (uname, subs, avg) in enumerate(rows, 1):
                logger.info("  %2d. @%-30s  %7d подп.  avg %5d просм.", i, uname, subs, avg)
        except Exception as e:
            logger.warning("Не удалось получить топ: %s", e)

    finally:
        await client.disconnect()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Адаптивный сканер статистики Telegram-каналов")
    parser.add_argument("--profile", required=True, choices=["ai", "marketplace"])
    args = parser.parse_args()
    os.environ["PROFILE"] = args.profile
    asyncio.run(main(args.profile))
