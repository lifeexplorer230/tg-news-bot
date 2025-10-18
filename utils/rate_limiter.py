"""Rate Limiter для защиты от превышения лимитов Telegram API"""

import asyncio
from collections import deque
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Простой rate limiter для Telegram API

    Telegram API limits:
    - 30 requests per second per bot
    - 20 messages per minute to same group
    - 1 message per second to same user

    Использование:
        limiter = RateLimiter(max_requests=20, per_seconds=60)
        await limiter.acquire()
        # делаем API запрос
    """

    def __init__(self, max_requests: int = 20, per_seconds: int = 60):
        """
        Args:
            max_requests: Максимальное количество запросов
            per_seconds: Период времени в секундах

        Raises:
            ValueError: If max_requests < 1 or per_seconds < 1
        """
        # Validate parameters to prevent edge cases
        if max_requests < 1:
            raise ValueError(f"max_requests должен быть >= 1, получено: {max_requests}")
        if per_seconds < 1:
            raise ValueError(f"per_seconds должен быть >= 1, получено: {per_seconds}")

        self.max_requests = max_requests
        self.per_seconds = per_seconds
        self.requests: deque[datetime] = deque()
        logger.info(
            "Rate limiter инициализирован: %d запросов / %d секунд",
            max_requests,
            per_seconds,
        )

    async def acquire(self):
        """
        Получить разрешение на выполнение запроса

        Блокирует выполнение если достигнут лимит, пока не освободится слот
        """
        now = datetime.now()

        # Удаляем старые запросы за пределами временного окна
        while self.requests and now - self.requests[0] > timedelta(seconds=self.per_seconds):
            self.requests.popleft()

        # Если достигнут лимит, ждём
        if len(self.requests) >= self.max_requests:
            # Вычисляем время ожидания до освобождения первого слота
            sleep_time = self.per_seconds - (now - self.requests[0]).total_seconds()
            if sleep_time > 0:
                logger.warning(
                    "Rate limit достигнут (%d/%d). Ожидание %.2f секунд...",
                    len(self.requests),
                    self.max_requests,
                    sleep_time,
                )
                await asyncio.sleep(sleep_time)
                return await self.acquire()

        # Регистрируем запрос
        self.requests.append(now)

    def reset(self):
        """Сбросить счётчик запросов"""
        self.requests.clear()
        logger.info("Rate limiter сброшен")

    @property
    def current_usage(self) -> int:
        """Получить текущее количество запросов в окне"""
        now = datetime.now()
        # Очищаем устаревшие
        while self.requests and now - self.requests[0] > timedelta(seconds=self.per_seconds):
            self.requests.popleft()
        return len(self.requests)

    def __repr__(self) -> str:
        return f"RateLimiter({self.current_usage}/{self.max_requests} in {self.per_seconds}s)"
