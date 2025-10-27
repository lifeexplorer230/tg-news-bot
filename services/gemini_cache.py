"""
LRU Cache с TTL для Gemini API ответов

Кэширование запросов к Gemini для снижения нагрузки и экономии API quota.
Использует LRU (Least Recently Used) с TTL (Time To Live) для автоматического
удаления устаревших записей.

Features:
- LRU cache с максимальным размером 1000 записей
- TTL 24 часа для каждой записи
- Thread-safe операции
- Автоматическая очистка устаревших записей
- Статистика hit/miss rate
- Хэширование запросов для уникальных ключей
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class CacheEntry:
    """
    Запись кэша с TTL

    Attributes:
        value: Закэшированное значение (JSON-совместимый объект)
        timestamp: Время создания записи (Unix timestamp)
        access_count: Количество обращений к записи
        last_access: Время последнего доступа (Unix timestamp)
    """

    value: Any
    timestamp: float
    access_count: int = 0
    last_access: float = 0.0

    def is_expired(self, ttl_seconds: float) -> bool:
        """
        Проверка истечения TTL

        Args:
            ttl_seconds: Время жизни записи в секундах

        Returns:
            True если запись устарела
        """
        return (time.time() - self.timestamp) > ttl_seconds

    def touch(self):
        """Обновить время последнего доступа"""
        self.last_access = time.time()
        self.access_count += 1


class GeminiCache:
    """
    LRU Cache с TTL для Gemini API

    Thread-safe кэш для хранения ответов Gemini API.
    Использует LRU для автоматического удаления старых записей при превышении max_size.
    TTL обеспечивает актуальность данных.

    Attributes:
        max_size: Максимальное количество записей (по умолчанию 1000)
        ttl_hours: Время жизни записи в часах (по умолчанию 24)

    Example:
        >>> cache = GeminiCache(max_size=1000, ttl_hours=24)
        >>> cache.set("prompt1", "response1")
        >>> result = cache.get("prompt1")
        >>> stats = cache.get_stats()
        >>> cache.clear()
    """

    DEFAULT_MAX_SIZE = 1000
    DEFAULT_TTL_HOURS = 24

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_SIZE,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        *,
        auto_cleanup: bool = True,
        cleanup_interval: int = 3600,
    ):
        """
        Инициализация кэша

        Args:
            max_size: Максимальное количество записей в кэше (1-10000)
            ttl_hours: Время жизни записи в часах (0.1-168)
            auto_cleanup: Автоматически очищать устаревшие записи
            cleanup_interval: Интервал автоочистки в секундах (по умолчанию 1 час)
        """
        self.max_size = max(1, min(max_size, 10000))
        self.ttl_seconds = max(0.1 * 3600, min(ttl_hours * 3600, 168 * 3600))

        # LRU cache: OrderedDict поддерживает порядок вставки
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()  # RLock для вложенных вызовов

        # Статистика
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,  # Удалено по LRU
            "expirations": 0,  # Удалено по TTL
            "total_sets": 0,
        }

        # Автоочистка
        self._auto_cleanup = auto_cleanup
        self._cleanup_interval = cleanup_interval
        self._cleanup_thread: threading.Thread | None = None
        self._stop_cleanup = threading.Event()

        if self._auto_cleanup:
            self._start_cleanup_thread()

        logger.info(
            f"Gemini cache инициализирован: max_size={self.max_size}, "
            f"ttl={ttl_hours}h, auto_cleanup={auto_cleanup}"
        )

    def _hash_key(self, prompt: str | dict) -> str:
        """
        Создать хэш-ключ для промпта

        Использует SHA256 для создания уникального короткого ключа.
        Поддерживает как строки, так и словари (JSON-сериализация).

        Args:
            prompt: Промпт (строка или словарь)

        Returns:
            Хэш-ключ (SHA256 hex digest)
        """
        if isinstance(prompt, dict):
            # Сериализуем с сортировкой ключей для консистентности
            prompt = json.dumps(prompt, sort_keys=True, ensure_ascii=False)

        # SHA256 hash
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get(self, prompt: str | dict) -> Any | None:
        """
        Получить значение из кэша

        Args:
            prompt: Промпт для поиска

        Returns:
            Закэшированное значение или None если не найдено/устарело

        Example:
            >>> result = cache.get("Analyze this text...")
            >>> if result is None:
            ...     result = call_gemini_api(...)
            ...     cache.set("Analyze this text...", result)
        """
        key = self._hash_key(prompt)

        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                logger.debug(f"Cache MISS: {key[:16]}...")
                return None

            entry = self._cache[key]

            # Проверяем TTL
            if entry.is_expired(self.ttl_seconds):
                logger.debug(f"Cache EXPIRED: {key[:16]}... (age: {time.time() - entry.timestamp:.1f}s)")
                del self._cache[key]
                self._stats["misses"] += 1
                self._stats["expirations"] += 1
                return None

            # Обновляем статистику доступа
            entry.touch()

            # Перемещаем в конец (most recently used)
            self._cache.move_to_end(key)

            self._stats["hits"] += 1
            logger.debug(
                f"Cache HIT: {key[:16]}... (age: {time.time() - entry.timestamp:.1f}s, "
                f"accesses: {entry.access_count})"
            )

            return entry.value

    def set(self, prompt: str | dict, value: Any):
        """
        Сохранить значение в кэш

        Args:
            prompt: Промпт (ключ)
            value: Значение для кэширования (должно быть JSON-сериализуемым)

        Example:
            >>> response = gemini_api.generate_content(prompt)
            >>> cache.set(prompt, response.text)
        """
        key = self._hash_key(prompt)

        with self._lock:
            # Если ключ уже есть, обновляем
            if key in self._cache:
                logger.debug(f"Cache UPDATE: {key[:16]}...")
                del self._cache[key]

            # Проверяем размер кэша
            if len(self._cache) >= self.max_size:
                # Удаляем самую старую запись (FIFO в OrderedDict)
                evicted_key, evicted_entry = self._cache.popitem(last=False)
                self._stats["evictions"] += 1
                logger.debug(
                    f"Cache EVICT (LRU): {evicted_key[:16]}... "
                    f"(age: {time.time() - evicted_entry.timestamp:.1f}s, "
                    f"accesses: {evicted_entry.access_count})"
                )

            # Добавляем новую запись
            entry = CacheEntry(
                value=value,
                timestamp=time.time(),
                access_count=0,
                last_access=time.time(),
            )
            self._cache[key] = entry
            self._stats["total_sets"] += 1

            logger.debug(
                f"Cache SET: {key[:16]}... (cache size: {len(self._cache)}/{self.max_size})"
            )

    def cleanup_expired(self) -> int:
        """
        Удалить все устаревшие записи

        Returns:
            Количество удалённых записей

        Example:
            >>> removed = cache.cleanup_expired()
            >>> print(f"Removed {removed} expired entries")
        """
        with self._lock:
            expired_keys = [
                key
                for key, entry in self._cache.items()
                if entry.is_expired(self.ttl_seconds)
            ]

            for key in expired_keys:
                del self._cache[key]
                self._stats["expirations"] += 1

            if expired_keys:
                logger.info(f"Очищено {len(expired_keys)} устаревших записей из кэша")

            return len(expired_keys)

    def _cleanup_loop(self):
        """Фоновый цикл очистки устаревших записей"""
        logger.info(f"Запущен фоновый поток очистки кэша (интервал: {self._cleanup_interval}s)")

        while not self._stop_cleanup.wait(self._cleanup_interval):
            try:
                removed = self.cleanup_expired()
                if removed > 0:
                    logger.debug(f"Автоочистка: удалено {removed} записей")
            except Exception as e:
                logger.error(f"Ошибка в фоновой очистке кэша: {e}")

        logger.info("Фоновый поток очистки кэша остановлен")

    def _start_cleanup_thread(self):
        """Запустить фоновый поток очистки"""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return

        self._stop_cleanup.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="GeminiCache-Cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def stop_cleanup_thread(self):
        """Остановить фоновый поток очистки"""
        if self._cleanup_thread is None:
            return

        logger.info("Останавливаем фоновый поток очистки кэша...")
        self._stop_cleanup.set()

        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

        self._cleanup_thread = None

    def get_stats(self) -> dict:
        """
        Получить статистику кэша

        Returns:
            Словарь со статистикой:
            - hits: Количество попаданий в кэш
            - misses: Количество промахов
            - hit_rate: Процент попаданий (0.0-1.0)
            - total_requests: Общее количество запросов
            - evictions: Удалено по LRU
            - expirations: Удалено по TTL
            - total_sets: Всего записей добавлено
            - current_size: Текущий размер кэша
            - max_size: Максимальный размер
            - ttl_hours: TTL в часах

        Example:
            >>> stats = cache.get_stats()
            >>> print(f"Hit rate: {stats['hit_rate']:.1%}")
        """
        with self._lock:
            stats = self._stats.copy()
            total_requests = stats["hits"] + stats["misses"]
            hit_rate = stats["hits"] / total_requests if total_requests > 0 else 0.0

            return {
                **stats,
                "hit_rate": hit_rate,
                "total_requests": total_requests,
                "current_size": len(self._cache),
                "max_size": self.max_size,
                "ttl_hours": self.ttl_seconds / 3600,
            }

    def clear(self):
        """
        Очистить весь кэш

        Example:
            >>> cache.clear()
            >>> assert cache.get_stats()["current_size"] == 0
        """
        with self._lock:
            size = len(self._cache)
            self._cache.clear()
            logger.info(f"Кэш полностью очищен (было {size} записей)")

    def reset_stats(self):
        """
        Сбросить статистику (но не очищать кэш)

        Example:
            >>> cache.reset_stats()
        """
        with self._lock:
            self._stats = {
                "hits": 0,
                "misses": 0,
                "evictions": 0,
                "expirations": 0,
                "total_sets": 0,
            }
            logger.info("Статистика кэша сброшена")

    def __len__(self) -> int:
        """Текущий размер кэша"""
        with self._lock:
            return len(self._cache)

    def __contains__(self, prompt: str | dict) -> bool:
        """Проверка наличия промпта в кэше (с учётом TTL)"""
        return self.get(prompt) is not None

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.stop_cleanup_thread()
        return False

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.stop_cleanup_thread()
        except Exception:
            pass


def create_gemini_cache(
    max_size: int = GeminiCache.DEFAULT_MAX_SIZE,
    ttl_hours: float = GeminiCache.DEFAULT_TTL_HOURS,
    **kwargs
) -> GeminiCache:
    """
    Фабричная функция для создания кэша

    Args:
        max_size: Максимальное количество записей
        ttl_hours: Время жизни записи в часах
        **kwargs: Дополнительные параметры для GeminiCache

    Returns:
        Настроенный кэш

    Example:
        >>> cache = create_gemini_cache(max_size=500, ttl_hours=12)
    """
    return GeminiCache(max_size=max_size, ttl_hours=ttl_hours, **kwargs)


if __name__ == "__main__":
    # Демонстрация использования
    import random

    print("=== Тест Gemini Cache ===\n")

    # Создаём кэш
    cache = create_gemini_cache(max_size=5, ttl_hours=0.001, auto_cleanup=False)  # 3.6s TTL для теста

    # Тест 1: Базовые операции
    print("1. Базовые операции:")
    cache.set("prompt1", {"response": "answer1"})
    cache.set("prompt2", {"response": "answer2"})

    result1 = cache.get("prompt1")
    result2 = cache.get("prompt3")  # miss

    print(f"   Get prompt1: {result1}")
    print(f"   Get prompt3 (miss): {result2}")
    print(f"   Cache size: {len(cache)}")

    # Тест 2: LRU eviction
    print("\n2. LRU eviction (max_size=5):")
    for i in range(6):
        cache.set(f"prompt_lru_{i}", {"response": f"answer_{i}"})
        print(f"   Added prompt_lru_{i}, cache size: {len(cache)}")

    # Тест 3: Статистика
    print("\n3. Статистика:")
    stats = cache.get_stats()
    for key, value in stats.items():
        if key == "hit_rate":
            print(f"   {key}: {value:.1%}")
        else:
            print(f"   {key}: {value}")

    # Тест 4: TTL expiration
    print("\n4. TTL expiration (wait 4s):")
    cache.clear()
    cache.set("short_lived", "expires soon")
    print(f"   Сразу после set: {cache.get('short_lived')}")

    time.sleep(4)  # Ждём истечения TTL
    print(f"   После 4s (TTL 3.6s): {cache.get('short_lived')}")

    # Тест 5: Cleanup
    print("\n5. Cleanup expired:")
    cache.clear()
    cache.set("will_expire", "value")
    time.sleep(4)
    cache.set("fresh", "new value")
    removed = cache.cleanup_expired()
    print(f"   Удалено устаревших: {removed}")
    print(f"   Cache size: {len(cache)}")

    # Тест 6: Словари как ключи
    print("\n6. Словари как ключи:")
    cache.set({"type": "analysis", "text": "sample"}, "result1")
    cache.set({"text": "sample", "type": "analysis"}, "result2")  # Тот же ключ
    result = cache.get({"type": "analysis", "text": "sample"})
    print(f"   Get dict key: {result}")
    print(f"   Cache size: {len(cache)}")

    # Тест 7: Параллельный доступ
    print("\n7. Thread-safe параллельный доступ:")
    cache.clear()

    def worker(worker_id: int):
        for i in range(10):
            prompt = f"worker_{worker_id}_prompt_{i % 3}"  # Повторяющиеся ключи
            result = cache.get(prompt)
            if result is None:
                cache.set(prompt, f"response_{worker_id}_{i}")
            time.sleep(random.uniform(0.001, 0.01))

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(5)]
        for future in futures:
            future.result()

    print(f"   После параллельной работы:")
    final_stats = cache.get_stats()
    print(f"   Hit rate: {final_stats['hit_rate']:.1%}")
    print(f"   Hits: {final_stats['hits']}, Misses: {final_stats['misses']}")
    print(f"   Cache size: {len(cache)}")

    print("\n=== Тест завершён ===")
