"""
Батчевая обработка сообщений для повышения производительности

Накапливает сообщения в батчи и обрабатывает их асинхронно.
Снижает количество транзакций к БД и API вызовов.

Features:
- Накопление до max_batch_size сообщений или max_wait_seconds
- Асинхронная обработка батчей
- Параллельная обработка где возможно
- Graceful shutdown с обработкой оставшихся сообщений
- Thread-safe операции
- Статистика обработки
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class BatchItem:
    """
    Элемент батча

    Attributes:
        data: Данные для обработки
        timestamp: Время добавления в батч (Unix timestamp)
        metadata: Дополнительные метаданные (опционально)
    """

    data: Any
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class BatchProcessor:
    """
    Батчевый процессор для асинхронной обработки сообщений

    Накапливает сообщения и обрабатывает их батчами для повышения
    производительности и снижения нагрузки на БД/API.

    Attributes:
        process_func: Функция для обработки батча
        max_batch_size: Максимальный размер батча (по умолчанию 100)
        max_wait_seconds: Максимальное время ожидания батча (по умолчанию 5)
        parallel_processing: Включить параллельную обработку внутри батча

    Example:
        >>> def process_batch(items):
        ...     for item in items:
        ...         print(f"Processing: {item.data}")
        ...
        >>> processor = BatchProcessor(process_batch, max_batch_size=50)
        >>> processor.start()
        >>> processor.add_item({"id": 1, "text": "message"})
        >>> processor.shutdown()
    """

    DEFAULT_MAX_BATCH_SIZE = 100
    DEFAULT_MAX_WAIT_SECONDS = 5.0

    def __init__(
        self,
        process_func: Callable[[list[BatchItem]], Any],
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
        parallel_processing: bool = False,
        max_workers: int = 4,
    ):
        """
        Инициализация батч-процессора

        Args:
            process_func: Функция для обработки батча items: list[BatchItem]
            max_batch_size: Максимальный размер батча (1-1000)
            max_wait_seconds: Максимальное время ожидания (0.1-60)
            parallel_processing: Включить параллельную обработку
            max_workers: Количество воркеров для параллельной обработки
        """
        self.process_func = process_func
        self.max_batch_size = max(1, min(max_batch_size, 1000))
        self.max_wait_seconds = max(0.1, min(max_wait_seconds, 60.0))
        self.parallel_processing = parallel_processing
        self.max_workers = max(1, min(max_workers, 10))

        # Thread-safe очередь для накопления элементов
        self._queue: deque[BatchItem] = deque()
        self._lock = threading.RLock()

        # Контроль потоков
        self._processing_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False

        # Статистика
        self._stats = {
            "items_added": 0,
            "items_processed": 0,
            "batches_processed": 0,
            "errors": 0,
            "last_batch_time": 0.0,
            "total_processing_time": 0.0,
        }
        self._stats_lock = threading.Lock()

        logger.info(
            f"Batch processor инициализирован: max_batch_size={self.max_batch_size}, "
            f"max_wait={self.max_wait_seconds}s, parallel={parallel_processing}"
        )

    def start(self):
        """
        Запустить процессор

        Запускает фоновый поток для обработки батчей.

        Example:
            >>> processor.start()
        """
        if self._running:
            logger.warning("Batch processor уже запущен")
            return

        self._stop_event.clear()
        self._running = True

        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            name="BatchProcessor",
            daemon=True,
        )
        self._processing_thread.start()

        logger.info("Batch processor запущен")

    def stop(self):
        """
        Остановить процессор (без обработки оставшихся элементов)

        Для graceful shutdown используйте shutdown().

        Example:
            >>> processor.stop()
        """
        if not self._running:
            return

        logger.info("Останавливаем batch processor...")
        self._stop_event.set()
        self._running = False

        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5)

        logger.info("Batch processor остановлен")

    def shutdown(self, timeout: float = 30.0):
        """
        Graceful shutdown: обрабатываем оставшиеся элементы и останавливаем

        Args:
            timeout: Максимальное время ожидания обработки (секунды)

        Example:
            >>> processor.shutdown(timeout=10.0)
        """
        if not self._running:
            logger.warning("Batch processor уже остановлен")
            return

        logger.info("Graceful shutdown batch processor...")

        with self._lock:
            queue_size = len(self._queue)

        if queue_size > 0:
            logger.info(f"Обрабатываем оставшиеся {queue_size} элементов...")

            start_time = time.time()
            while len(self._queue) > 0 and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            remaining = len(self._queue)
            if remaining > 0:
                logger.warning(
                    f"Shutdown timeout: {remaining} элементов не обработаны за {timeout}s"
                )
            else:
                logger.info("Все элементы обработаны")

        self.stop()

    def add_item(self, data: Any, metadata: dict | None = None):
        """
        Добавить элемент в очередь обработки

        Args:
            data: Данные для обработки
            metadata: Дополнительные метаданные (опционально)

        Example:
            >>> processor.add_item({"id": 1, "text": "message"})
            >>> processor.add_item(message, metadata={"priority": "high"})
        """
        if not self._running:
            raise RuntimeError("Batch processor не запущен. Вызовите start() сначала.")

        item = BatchItem(data=data, timestamp=time.time(), metadata=metadata or {})

        with self._lock:
            self._queue.append(item)
            queue_size = len(self._queue)

        with self._stats_lock:
            self._stats["items_added"] += 1

        logger.debug(f"Добавлен элемент в очередь (размер: {queue_size})")

    def _get_batch(self) -> list[BatchItem]:
        """
        Получить батч для обработки

        Собирает батч на основе max_batch_size или max_wait_seconds.

        Returns:
            Список элементов для обработки
        """
        with self._lock:
            if not self._queue:
                return []

            # Проверяем размер
            if len(self._queue) >= self.max_batch_size:
                batch = [self._queue.popleft() for _ in range(self.max_batch_size)]
                logger.debug(f"Батч собран по размеру: {len(batch)} элементов")
                return batch

            # Проверяем время ожидания
            oldest_item = self._queue[0]
            wait_time = time.time() - oldest_item.timestamp

            if wait_time >= self.max_wait_seconds:
                # Забираем все доступные элементы (до max_batch_size)
                batch_size = min(len(self._queue), self.max_batch_size)
                batch = [self._queue.popleft() for _ in range(batch_size)]
                logger.debug(
                    f"Батч собран по таймауту ({wait_time:.1f}s): {len(batch)} элементов"
                )
                return batch

            return []

    def _process_batch(self, batch: list[BatchItem]):
        """
        Обработать батч элементов

        Args:
            batch: Список элементов для обработки
        """
        if not batch:
            return

        batch_size = len(batch)
        start_time = time.time()

        try:
            logger.info(f"Обработка батча: {batch_size} элементов")

            if self.parallel_processing:
                self._process_batch_parallel(batch)
            else:
                # Последовательная обработка
                self.process_func(batch)

            duration = time.time() - start_time

            with self._stats_lock:
                self._stats["items_processed"] += batch_size
                self._stats["batches_processed"] += 1
                self._stats["last_batch_time"] = duration
                self._stats["total_processing_time"] += duration

            logger.info(
                f"Батч обработан успешно: {batch_size} элементов за {duration:.2f}s "
                f"({batch_size/duration:.1f} items/s)"
            )

        except Exception as e:
            logger.error(f"Ошибка обработки батча ({batch_size} элементов): {e}")

            with self._stats_lock:
                self._stats["errors"] += 1

            # Опционально: можно вернуть элементы в очередь или сохранить в dead letter queue
            # Здесь просто логируем ошибку

    def _process_batch_parallel(self, batch: list[BatchItem]):
        """
        Параллельная обработка батча

        Args:
            batch: Список элементов для обработки
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.debug(f"Параллельная обработка батча с {self.max_workers} воркерами")

        # Разбиваем батч на чанки для воркеров
        chunk_size = max(1, len(batch) // self.max_workers)
        chunks = [batch[i : i + chunk_size] for i in range(0, len(batch), chunk_size)]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self.process_func, chunk) for chunk in chunks]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Ошибка в параллельном воркере: {e}")
                    raise

    def _processing_loop(self):
        """Основной цикл обработки батчей"""
        logger.info("Запущен цикл обработки батчей")

        # Используем короткий интервал проверки для responsive shutdown
        check_interval = min(0.1, self.max_wait_seconds / 10)

        while not self._stop_event.is_set():
            try:
                batch = self._get_batch()

                if batch:
                    self._process_batch(batch)
                else:
                    # Нет батча для обработки, ждём
                    time.sleep(check_interval)

            except Exception as e:
                logger.error(f"Ошибка в цикле обработки: {e}")
                time.sleep(1)  # Предотвращаем tight loop при ошибках

        # Обрабатываем оставшиеся элементы при shutdown
        logger.info("Обработка оставшихся батчей при shutdown...")
        while True:
            with self._lock:
                if not self._queue:
                    break
                batch = [
                    self._queue.popleft()
                    for _ in range(min(len(self._queue), self.max_batch_size))
                ]

            if batch:
                self._process_batch(batch)

        logger.info("Цикл обработки батчей завершён")

    def get_stats(self) -> dict:
        """
        Получить статистику обработки

        Returns:
            Словарь со статистикой:
            - items_added: Всего элементов добавлено
            - items_processed: Всего элементов обработано
            - items_pending: Элементов в очереди
            - batches_processed: Батчей обработано
            - errors: Количество ошибок
            - avg_batch_size: Средний размер батча
            - last_batch_time: Время обработки последнего батча (секунды)
            - total_processing_time: Общее время обработки
            - throughput: Пропускная способность (items/s)

        Example:
            >>> stats = processor.get_stats()
            >>> print(f"Throughput: {stats['throughput']:.1f} items/s")
        """
        with self._stats_lock:
            stats = self._stats.copy()

        with self._lock:
            stats["items_pending"] = len(self._queue)

        # Вычисляем производные метрики
        batches = stats["batches_processed"]
        items = stats["items_processed"]
        total_time = stats["total_processing_time"]

        stats["avg_batch_size"] = items / batches if batches > 0 else 0.0
        stats["throughput"] = items / total_time if total_time > 0 else 0.0
        stats["is_running"] = self._running

        return stats

    def reset_stats(self):
        """
        Сбросить статистику (без очистки очереди)

        Example:
            >>> processor.reset_stats()
        """
        with self._stats_lock:
            self._stats = {
                "items_added": 0,
                "items_processed": 0,
                "batches_processed": 0,
                "errors": 0,
                "last_batch_time": 0.0,
                "total_processing_time": 0.0,
            }
        logger.info("Статистика batch processor сброшена")

    def __len__(self) -> int:
        """Количество элементов в очереди"""
        with self._lock:
            return len(self._queue)

    def __enter__(self):
        """Context manager support"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.shutdown()
        return False

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.stop()
        except Exception:
            pass


def create_batch_processor(
    process_func: Callable[[list[BatchItem]], Any],
    max_batch_size: int = BatchProcessor.DEFAULT_MAX_BATCH_SIZE,
    max_wait_seconds: float = BatchProcessor.DEFAULT_MAX_WAIT_SECONDS,
    **kwargs
) -> BatchProcessor:
    """
    Фабричная функция для создания батч-процессора

    Args:
        process_func: Функция для обработки батча
        max_batch_size: Максимальный размер батча
        max_wait_seconds: Максимальное время ожидания
        **kwargs: Дополнительные параметры для BatchProcessor

    Returns:
        Настроенный батч-процессор

    Example:
        >>> def my_processor(items):
        ...     for item in items:
        ...         print(item.data)
        ...
        >>> processor = create_batch_processor(my_processor, max_batch_size=50)
        >>> processor.start()
    """
    return BatchProcessor(
        process_func,
        max_batch_size=max_batch_size,
        max_wait_seconds=max_wait_seconds,
        **kwargs,
    )


if __name__ == "__main__":
    # Демонстрация использования
    import random

    print("=== Тест Batch Processor ===\n")

    processed_items = []

    def process_batch(items: list[BatchItem]):
        """Тестовая функция обработки"""
        print(f"  Обработка батча: {len(items)} элементов")
        for item in items:
            processed_items.append(item.data)
            # Имитация работы
            time.sleep(0.01)

    # Тест 1: Базовая работа
    print("1. Базовая работа (10 элементов, batch_size=5):")
    processor = create_batch_processor(
        process_batch, max_batch_size=5, max_wait_seconds=2.0
    )
    processor.start()

    for i in range(10):
        processor.add_item({"id": i, "message": f"msg_{i}"})
        time.sleep(0.1)

    time.sleep(1)  # Ждём обработки

    stats = processor.get_stats()
    print(f"   Обработано: {stats['items_processed']}/{stats['items_added']}")
    print(f"   Батчей: {stats['batches_processed']}")
    print(f"   Avg batch size: {stats['avg_batch_size']:.1f}")

    processor.shutdown()

    # Тест 2: Таймаут батча
    print("\n2. Таймаут батча (3 элемента, wait=2s):")
    processed_items.clear()
    processor = create_batch_processor(
        process_batch, max_batch_size=100, max_wait_seconds=2.0
    )
    processor.start()

    for i in range(3):
        processor.add_item({"id": i})

    print("   Ждём 2.5 секунды...")
    time.sleep(2.5)

    stats = processor.get_stats()
    print(f"   Обработано по таймауту: {stats['items_processed']}")

    processor.shutdown()

    # Тест 3: Параллельная обработка
    print("\n3. Параллельная обработка (50 элементов, 4 воркера):")
    processed_items.clear()

    def parallel_process(items: list[BatchItem]):
        thread_id = threading.current_thread().ident
        print(f"  Thread {thread_id}: обработка {len(items)} элементов")
        for item in items:
            processed_items.append(item.data)
            time.sleep(0.01)

    processor = create_batch_processor(
        parallel_process,
        max_batch_size=50,
        max_wait_seconds=1.0,
        parallel_processing=True,
        max_workers=4,
    )
    processor.start()

    for i in range(50):
        processor.add_item({"id": i})

    time.sleep(2)

    stats = processor.get_stats()
    print(f"   Обработано: {stats['items_processed']}")
    print(f"   Throughput: {stats['throughput']:.1f} items/s")

    processor.shutdown()

    # Тест 4: Graceful shutdown
    print("\n4. Graceful shutdown (добавляем много элементов):")
    processed_items.clear()

    def slow_process(items: list[BatchItem]):
        print(f"  Медленная обработка: {len(items)} элементов")
        time.sleep(0.5)  # Медленная обработка
        for item in items:
            processed_items.append(item.data)

    processor = create_batch_processor(
        slow_process, max_batch_size=10, max_wait_seconds=1.0
    )
    processor.start()

    # Добавляем 25 элементов
    for i in range(25):
        processor.add_item({"id": i})

    print(f"   Добавлено 25 элементов")
    print(f"   Graceful shutdown...")

    processor.shutdown(timeout=10.0)

    print(f"   Обработано после shutdown: {len(processed_items)}")

    # Тест 5: Context manager
    print("\n5. Context manager:")
    processed_items.clear()

    with create_batch_processor(process_batch, max_batch_size=5) as processor:
        for i in range(8):
            processor.add_item({"id": i})
        time.sleep(1)

    print(f"   Обработано: {len(processed_items)}")

    print("\n=== Тест завершён ===")
