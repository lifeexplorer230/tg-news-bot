"""
Улучшенный многоуровневый rate limiter для Telegram API.

Обеспечивает защиту от превышения лимитов на нескольких уровнях:
- Global: Общий лимит запросов (30 req/sec)
- Burst: Защита от всплесков (100 req/10sec)
- Per-chat: Лимит на конкретный чат (20 msg/min)
- FloodWait: Адаптивная обработка Telegram flood errors
"""

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional

from utils.logger import setup_logger

logger = setup_logger(__name__)


class TokenBucket:
    """Реализация алгоритма Token Bucket для rate limiting"""

    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Скорость пополнения токенов (токенов в секунду)
            capacity: Максимальная емкость корзины
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> float:
        """
        Получить токены из корзины.

        Args:
            tokens: Количество требуемых токенов

        Returns:
            Время ожидания в секундах (0 если токены доступны сразу)
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update

            # Пополняем токены
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            # Вычисляем время ожидания
            wait_time = (tokens - self.tokens) / self.rate
            return wait_time


class SlidingWindowRateLimiter:
    """Rate limiter с sliding window алгоритмом"""

    def __init__(self, max_requests: int, window_seconds: float):
        """
        Args:
            max_requests: Максимум запросов в окне
            window_seconds: Размер окна в секундах
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Проверить и записать запрос.

        Returns:
            Время ожидания в секундах (0 если можно выполнять сразу)
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds

            # Удаляем старые запросы
            while self.requests and self.requests[0] < cutoff:
                self.requests.popleft()

            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return 0.0

            # Вычисляем время ожидания
            oldest_request = self.requests[0]
            wait_time = self.window_seconds - (now - oldest_request) + 0.01
            return max(0, wait_time)


class MultiLevelRateLimiter:
    """
    Многоуровневый rate limiter для Telegram API.

    Уровни защиты:
    1. Global rate limit (30 req/sec)
    2. Burst protection (100 req/10sec)
    3. Per-chat limits (20 msg/min per chat)
    4. Adaptive FloodWait handling
    """

    def __init__(self):
        # Global limits
        self.global_limiter = TokenBucket(rate=30, capacity=30)  # 30 req/sec
        self.burst_limiter = SlidingWindowRateLimiter(
            max_requests=100, window_seconds=10
        )  # 100 req/10sec

        # Per-chat limiters
        self.per_chat_limiters: Dict[int, SlidingWindowRateLimiter] = {}

        # FloodWait tracking
        self.flood_wait_until: Dict[str, datetime] = {}
        self.flood_wait_multiplier: Dict[str, float] = {}  # Adaptive backoff

        # Статистика
        self.stats = {
            "total_requests": 0,
            "total_wait_time": 0.0,
            "flood_waits": 0,
            "max_wait_time": 0.0,
        }

    async def acquire(
        self,
        chat_id: Optional[int] = None,
        endpoint: Optional[str] = None,
        priority: int = 0,
    ) -> None:
        """
        Получить разрешение на выполнение запроса.

        Args:
            chat_id: ID чата (для per-chat limiting)
            endpoint: Название endpoint'а (для FloodWait tracking)
            priority: Приоритет запроса (0 - обычный, 1 - важный, 2 - критический)
        """
        wait_times = []

        # 1. Проверяем FloodWait
        if endpoint:
            flood_wait = await self._check_flood_wait(endpoint)
            if flood_wait > 0:
                wait_times.append(flood_wait)

        # 2. Global rate limit
        global_wait = await self.global_limiter.acquire()
        wait_times.append(global_wait)

        # 3. Burst protection
        burst_wait = await self.burst_limiter.acquire()
        wait_times.append(burst_wait)

        # 4. Per-chat rate limit
        if chat_id is not None:
            chat_wait = await self._get_chat_limiter(chat_id).acquire()
            wait_times.append(chat_wait)

        # Выбираем максимальное время ожидания
        total_wait = max(wait_times)

        # Применяем приоритет (критические запросы ждут меньше)
        if priority > 0:
            total_wait = total_wait * (1.0 / (priority + 1))

        # Ждем если необходимо
        if total_wait > 0:
            logger.debug(
                f"Rate limit: waiting {total_wait:.2f}s "
                f"(chat={chat_id}, endpoint={endpoint}, priority={priority})"
            )

            # Обновляем статистику
            self.stats["total_wait_time"] += total_wait
            self.stats["max_wait_time"] = max(self.stats["max_wait_time"], total_wait)

            await asyncio.sleep(total_wait)

        self.stats["total_requests"] += 1

    async def _check_flood_wait(self, endpoint: str) -> float:
        """Проверить FloodWait для endpoint'а"""
        if endpoint not in self.flood_wait_until:
            return 0.0

        wait_until = self.flood_wait_until[endpoint]
        now = datetime.now()

        if wait_until > now:
            wait_seconds = (wait_until - now).total_seconds()
            return wait_seconds

        # Очищаем истекший FloodWait
        del self.flood_wait_until[endpoint]
        if endpoint in self.flood_wait_multiplier:
            # Уменьшаем multiplier после успешного ожидания
            self.flood_wait_multiplier[endpoint] *= 0.5
            if self.flood_wait_multiplier[endpoint] < 1.0:
                del self.flood_wait_multiplier[endpoint]

        return 0.0

    def _get_chat_limiter(self, chat_id: int) -> SlidingWindowRateLimiter:
        """Получить или создать limiter для чата"""
        if chat_id not in self.per_chat_limiters:
            # 20 сообщений в минуту на чат (Telegram limit)
            self.per_chat_limiters[chat_id] = SlidingWindowRateLimiter(
                max_requests=20, window_seconds=60
            )
        return self.per_chat_limiters[chat_id]

    async def handle_flood_wait(self, wait_seconds: int, endpoint: str) -> None:
        """
        Обработать FloodWait ошибку от Telegram.

        Args:
            wait_seconds: Время ожидания от Telegram
            endpoint: Endpoint который вызвал ошибку
        """
        # Adaptive backoff: увеличиваем время ожидания с каждой ошибкой
        multiplier = self.flood_wait_multiplier.get(endpoint, 1.0)
        adjusted_wait = wait_seconds * multiplier

        # Устанавливаем время окончания ожидания
        wait_until = datetime.now() + timedelta(seconds=adjusted_wait)
        self.flood_wait_until[endpoint] = wait_until

        # Увеличиваем multiplier для следующего раза
        self.flood_wait_multiplier[endpoint] = min(multiplier * 1.5, 5.0)

        # Статистика
        self.stats["flood_waits"] += 1

        logger.warning(
            f"FloodWait: {wait_seconds}s for {endpoint} "
            f"(adjusted: {adjusted_wait:.1f}s, multiplier: {multiplier:.1f})"
        )

    def get_stats(self) -> dict:
        """Получить статистику rate limiter'а"""
        stats = self.stats.copy()

        # Добавляем текущее состояние
        stats["active_flood_waits"] = len(self.flood_wait_until)
        stats["tracked_chats"] = len(self.per_chat_limiters)

        if stats["total_requests"] > 0:
            stats["avg_wait_time"] = stats["total_wait_time"] / stats["total_requests"]
        else:
            stats["avg_wait_time"] = 0.0

        return stats

    async def cleanup_old_limiters(self, max_age_hours: int = 1) -> None:
        """
        Очистить старые per-chat limiters для экономии памяти.

        Args:
            max_age_hours: Максимальный возраст неактивных limiters
        """
        cutoff = time.monotonic() - (max_age_hours * 3600)
        to_remove = []

        for chat_id, limiter in self.per_chat_limiters.items():
            # Проверяем время последнего запроса
            if limiter.requests and limiter.requests[-1] < cutoff:
                to_remove.append(chat_id)

        for chat_id in to_remove:
            del self.per_chat_limiters[chat_id]

        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} old chat limiters")


class AdaptiveRateLimiter:
    """
    Адаптивный rate limiter который автоматически подстраивается
    под текущую нагрузку и ответы сервера.
    """

    def __init__(self, base_limiter: MultiLevelRateLimiter):
        self.base_limiter = base_limiter
        self.success_rate = 1.0
        self.adjustment_factor = 1.0
        self.history_window = 100
        self.request_history: deque = deque(maxlen=self.history_window)

    async def acquire(self, **kwargs) -> None:
        """Адаптивное получение разрешения"""
        # Применяем adjustment factor
        adjusted_wait = await self._get_adjusted_wait(**kwargs)
        if adjusted_wait > 0:
            await asyncio.sleep(adjusted_wait)

        await self.base_limiter.acquire(**kwargs)

    async def _get_adjusted_wait(self, **kwargs) -> float:
        """Вычислить адаптированное время ожидания"""
        # Базовая задержка с учетом adjustment
        base_delay = 0.033 * self.adjustment_factor  # ~30 req/sec adjusted

        return base_delay

    def record_result(self, success: bool) -> None:
        """Записать результат запроса для адаптации"""
        self.request_history.append(success)

        # Пересчитываем success rate
        if len(self.request_history) >= 10:
            self.success_rate = sum(self.request_history) / len(self.request_history)

            # Обновляем adjustment_factor на основе success_rate
            # Если success rate низкий, увеличиваем задержки
            if self.success_rate < 0.9:
                self.adjustment_factor = min(self.adjustment_factor * 1.1, 2.0)
            elif self.success_rate > 0.95:
                self.adjustment_factor = max(self.adjustment_factor * 0.95, 0.5)

    def get_status(self) -> dict:
        """Получить статус адаптивного limiter'а"""
        return {
            "success_rate": self.success_rate,
            "adjustment_factor": self.adjustment_factor,
            "history_size": len(self.request_history),
            **self.base_limiter.get_stats(),
        }