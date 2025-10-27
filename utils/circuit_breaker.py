"""
Circuit Breaker pattern implementation for external services.

Защищает от каскадных сбоев при недоступности внешних сервисов:
- Telegram API
- Gemini API
- Perplexity API

Состояния Circuit Breaker:
- CLOSED: Нормальная работа, запросы проходят
- OPEN: Сервис недоступен, запросы блокируются
- HALF_OPEN: Проверка восстановления сервиса
"""

import asyncio
import time
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, Union

from utils.logger import setup_logger

logger = setup_logger(__name__)


class CircuitState(Enum):
    """Состояния Circuit Breaker"""

    CLOSED = "closed"  # Нормальная работа
    OPEN = "open"  # Сервис недоступен
    HALF_OPEN = "half_open"  # Проверка восстановления


class CircuitBreakerError(Exception):
    """Исключение когда Circuit Breaker открыт"""

    def __init__(self, service: str, wait_time: float):
        self.service = service
        self.wait_time = wait_time
        super().__init__(
            f"Circuit breaker for {service} is OPEN. "
            f"Service will be available in {wait_time:.1f} seconds"
        )


class CircuitBreaker:
    """
    Реализация паттерна Circuit Breaker.

    Защищает от каскадных сбоев при недоступности внешних сервисов.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exceptions: tuple[Type[Exception], ...] = (Exception,),
        success_threshold: int = 2,
        half_open_max_calls: int = 3,
    ):
        """
        Args:
            name: Имя сервиса для логирования
            failure_threshold: Количество ошибок для открытия circuit
            recovery_timeout: Время ожидания перед попыткой восстановления (сек)
            expected_exceptions: Исключения которые считаются ошибками сервиса
            success_threshold: Успешных вызовов для закрытия из HALF_OPEN
            half_open_max_calls: Макс вызовов в состоянии HALF_OPEN
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        self.success_threshold = success_threshold
        self.half_open_max_calls = half_open_max_calls

        # Состояние
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0

        # Статистика
        self.stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "rejected_calls": 0,
            "state_changes": [],
            "last_error": None,
        }

        # Lock для thread safety
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Выполнить функцию через Circuit Breaker.

        Args:
            func: Функция для выполнения
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы

        Returns:
            Результат функции

        Raises:
            CircuitBreakerError: Если circuit открыт
            Exception: Оригинальное исключение от функции
        """
        async with self._lock:
            self.stats["total_calls"] += 1

            # Проверяем состояние
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    self.stats["rejected_calls"] += 1
                    wait_time = self.recovery_timeout - (
                        time.time() - self.last_failure_time
                    )
                    raise CircuitBreakerError(self.name, wait_time)

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    self.stats["rejected_calls"] += 1
                    raise CircuitBreakerError(self.name, 0)
                self.half_open_calls += 1

        # Выполняем функцию
        try:
            # Поддержка async и sync функций
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = await asyncio.to_thread(func, *args, **kwargs)

            await self._on_success()
            return result

        except self.expected_exceptions as e:
            await self._on_failure(e)
            raise

    async def _on_success(self):
        """Обработка успешного вызова"""
        async with self._lock:
            self.stats["successful_calls"] += 1
            self.failure_count = 0

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self._transition_to_closed()
                    logger.info(
                        f"Circuit breaker '{self.name}' CLOSED after recovery"
                    )

    async def _on_failure(self, exception: Exception):
        """Обработка неудачного вызова"""
        async with self._lock:
            self.stats["failed_calls"] += 1
            self.stats["last_error"] = str(exception)
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self._transition_to_open()
                logger.warning(
                    f"Circuit breaker '{self.name}' reopened after failure in HALF_OPEN"
                )
            elif (
                self.state == CircuitState.CLOSED
                and self.failure_count >= self.failure_threshold
            ):
                self._transition_to_open()
                logger.error(
                    f"Circuit breaker '{self.name}' OPEN after "
                    f"{self.failure_count} failures. Last error: {exception}"
                )

    def _should_attempt_reset(self) -> bool:
        """Проверить, пора ли попытаться восстановиться"""
        return (
            self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self.recovery_timeout
        )

    def _transition_to_closed(self):
        """Переход в состояние CLOSED"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        self._record_state_change("CLOSED")

    def _transition_to_open(self):
        """Переход в состояние OPEN"""
        self.state = CircuitState.OPEN
        self.success_count = 0
        self.half_open_calls = 0
        self._record_state_change("OPEN")

    def _transition_to_half_open(self):
        """Переход в состояние HALF_OPEN"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0
        self._record_state_change("HALF_OPEN")
        logger.info(f"Circuit breaker '{self.name}' attempting recovery (HALF_OPEN)")

    def _record_state_change(self, new_state: str):
        """Записать изменение состояния"""
        self.stats["state_changes"].append({
            "state": new_state,
            "timestamp": datetime.now().isoformat(),
        })
        # Храним только последние 100 изменений
        if len(self.stats["state_changes"]) > 100:
            self.stats["state_changes"] = self.stats["state_changes"][-100:]

    def get_status(self) -> dict:
        """Получить текущий статус Circuit Breaker"""
        status = {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            **self.stats,
        }

        if self.state == CircuitState.OPEN and self.last_failure_time:
            status["recovery_in"] = max(
                0,
                self.recovery_timeout - (time.time() - self.last_failure_time)
            )

        return status

    def reset(self):
        """Принудительный сброс в состояние CLOSED"""
        self._transition_to_closed()
        logger.info(f"Circuit breaker '{self.name}' manually reset")


def circuit_breaker(
    name: Optional[str] = None,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Декоратор для применения Circuit Breaker к функции.

    Usage:
        @circuit_breaker(name="telegram_api", failure_threshold=3)
        async def send_telegram_message(text):
            # ... код отправки ...

    Args:
        name: Имя circuit breaker (по умолчанию имя функции)
        failure_threshold: Порог ошибок
        recovery_timeout: Время восстановления
        expected_exceptions: Ожидаемые исключения
    """

    def decorator(func: Callable) -> Callable:
        cb_name = name or func.__name__
        cb = CircuitBreaker(
            name=cb_name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exceptions=expected_exceptions,
        )

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await cb.call(func, *args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Для синхронных функций создаем event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(cb.call(func, *args, **kwargs))

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class CircuitBreakerRegistry:
    """Реестр всех Circuit Breakers в приложении"""

    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def register(cls, breaker: CircuitBreaker):
        """Зарегистрировать Circuit Breaker"""
        cls._breakers[breaker.name] = breaker

    @classmethod
    def get(cls, name: str) -> Optional[CircuitBreaker]:
        """Получить Circuit Breaker по имени"""
        return cls._breakers.get(name)

    @classmethod
    def get_all_status(cls) -> Dict[str, dict]:
        """Получить статус всех Circuit Breakers"""
        return {name: breaker.get_status() for name, breaker in cls._breakers.items()}

    @classmethod
    def reset_all(cls):
        """Сбросить все Circuit Breakers"""
        for breaker in cls._breakers.values():
            breaker.reset()


class ServiceCircuitBreakers:
    """Предопределенные Circuit Breakers для внешних сервисов"""

    # Telegram API
    telegram_api = CircuitBreaker(
        name="telegram_api",
        failure_threshold=5,  # 5 ошибок
        recovery_timeout=60,  # 1 минута
        expected_exceptions=(Exception,),  # TODO: уточнить конкретные исключения
        success_threshold=3,  # 3 успеха для восстановления
    )

    # Gemini API
    gemini_api = CircuitBreaker(
        name="gemini_api",
        failure_threshold=3,  # 3 ошибки (дорогой API)
        recovery_timeout=120,  # 2 минуты
        expected_exceptions=(Exception,),  # TODO: уточнить конкретные исключения
        success_threshold=2,  # 2 успеха для восстановления
    )

    # Database
    database = CircuitBreaker(
        name="database",
        failure_threshold=10,  # 10 ошибок (локальная БД)
        recovery_timeout=30,  # 30 секунд
        expected_exceptions=(Exception,),  # TODO: sqlite3 exceptions
        success_threshold=5,  # 5 успехов для восстановления
    )

    @classmethod
    def register_all(cls):
        """Зарегистрировать все Circuit Breakers"""
        CircuitBreakerRegistry.register(cls.telegram_api)
        CircuitBreakerRegistry.register(cls.gemini_api)
        CircuitBreakerRegistry.register(cls.database)

    @classmethod
    def get_health_status(cls) -> dict:
        """Получить общий статус здоровья сервисов"""
        all_status = CircuitBreakerRegistry.get_all_status()

        healthy_count = sum(
            1 for status in all_status.values()
            if status["state"] == CircuitState.CLOSED.value
        )

        return {
            "healthy": healthy_count == len(all_status),
            "services_total": len(all_status),
            "services_healthy": healthy_count,
            "services_unhealthy": len(all_status) - healthy_count,
            "details": all_status,
        }


# Инициализация при импорте
ServiceCircuitBreakers.register_all()