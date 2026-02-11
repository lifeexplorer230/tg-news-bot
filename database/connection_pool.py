"""
Connection Pool для SQLite с thread-safe доступом и оптимизациями

Обеспечивает эффективное управление соединениями к SQLite БД с поддержкой:
- Пулинга соединений (максимум 5)
- WAL mode для параллельных операций
- Thread-safe контекстного менеджера
- Автоматической переконфигурации соединений
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Generator

from utils.logger import setup_logger

logger = setup_logger(__name__)


class ConnectionPool:
    """
    Thread-safe пул соединений для SQLite

    Управляет пулом до MAX_CONNECTIONS соединений к SQLite БД.
    Использует WAL mode для параллельного чтения/записи.

    Attributes:
        db_path: Путь к файлу базы данных
        max_connections: Максимальное количество соединений (по умолчанию 5)
        timeout: Таймаут ожидания свободного соединения (секунды)
        busy_timeout_ms: SQLite busy timeout в миллисекундах

    Example:
        >>> pool = ConnectionPool("data/bot.db", max_connections=5)
        >>> with pool.get_connection() as conn:
        ...     cursor = conn.cursor()
        ...     cursor.execute("SELECT * FROM channels")
        ...     results = cursor.fetchall()
        >>> pool.close_all()
    """

    DEFAULT_MAX_CONNECTIONS = 5
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_BUSY_TIMEOUT_MS = 30000

    def __init__(
        self,
        db_path: str,
        *,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        timeout: float = DEFAULT_TIMEOUT,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ):
        """
        Инициализация пула соединений

        Args:
            db_path: Путь к файлу SQLite БД
            max_connections: Максимальное количество соединений в пуле (1-10)
            timeout: Таймаут получения соединения из пула (секунды)
            busy_timeout_ms: SQLite busy_timeout в миллисекундах
        """
        self.db_path = Path(db_path)
        self.max_connections = max(1, min(max_connections, 10))  # Ограничиваем 1-10
        self.timeout = float(timeout)
        self.busy_timeout_ms = int(busy_timeout_ms)

        # Thread-safe очередь доступных соединений
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=self.max_connections)
        self._all_connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._closed = False

        # Статистика использования
        self._stats = {
            "connections_created": 0,
            "connections_reused": 0,
            "pool_waits": 0,
            "active_connections": 0,
        }
        self._stats_lock = threading.Lock()

        # Для :memory: используем shared cache чтобы все соединения видели одну БД
        self._is_memory = str(self.db_path) == ":memory:"
        if self._is_memory:
            self._connect_str = "file::memory:?cache=shared"
            self._connect_kwargs = {"uri": True}
        else:
            self._connect_str = str(self.db_path)
            self._connect_kwargs = {}
            # Создаём директорию если нужно
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Инициализируем WAL mode (пропускаем для :memory:)
        if not self._is_memory:
            self._initialize_wal_mode()

        logger.info(
            f"Connection pool инициализирован: {self.db_path}, "
            f"max_connections={self.max_connections}, timeout={self.timeout}s"
        )

    def _initialize_wal_mode(self):
        """
        Инициализация WAL mode для БД

        WAL (Write-Ahead Logging) позволяет параллельно читать и писать в БД.
        Вызывается один раз при создании пула.
        """
        try:
            conn = sqlite3.connect(self._connect_str, timeout=self.timeout, **self._connect_kwargs)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")  # Оптимизация для WAL
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA temp_store=MEMORY")  # Временные таблицы в памяти
            conn.close()
            logger.info("WAL mode включен для БД")
        except Exception as e:
            logger.error(f"Ошибка инициализации WAL mode: {e}")
            raise

    def _create_connection(self) -> sqlite3.Connection:
        """
        Создать новое соединение с оптимальными настройками

        Returns:
            Новое соединение к SQLite БД
        """
        conn = sqlite3.connect(
            self._connect_str,
            timeout=self.timeout,
            check_same_thread=False,  # Thread-safe соединение
            isolation_level=None,  # Autocommit mode для лучшей производительности
            **self._connect_kwargs,
        )

        # Применяем оптимизации
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.row_factory = sqlite3.Row  # Доступ по именам столбцов

        with self._stats_lock:
            self._stats["connections_created"] += 1

        logger.debug(f"Создано новое соединение (всего создано: {self._stats['connections_created']})")
        return conn

    def _get_or_create_connection(self) -> sqlite3.Connection:
        """
        Получить соединение из пула или создать новое

        Returns:
            Соединение к БД

        Raises:
            RuntimeError: Если пул закрыт
            TimeoutError: Если не удалось получить соединение за timeout
        """
        if self._closed:
            raise RuntimeError("Connection pool закрыт")

        # Пытаемся получить из пула
        try:
            conn = self._pool.get_nowait()
            with self._stats_lock:
                self._stats["connections_reused"] += 1
            logger.debug("Переиспользовано соединение из пула")
            return conn
        except Empty:
            pass

        # Проверяем, можно ли создать новое соединение
        with self._lock:
            current_count = len(self._all_connections)
            if current_count < self.max_connections:
                # Создаём новое соединение
                conn = self._create_connection()
                self._all_connections.append(conn)
                return conn

        # Пул заполнен, ждём освобождения
        with self._stats_lock:
            self._stats["pool_waits"] += 1

        logger.debug(
            f"Пул заполнен ({self.max_connections} соединений), ожидание освобождения..."
        )

        try:
            conn = self._pool.get(timeout=self.timeout)
            with self._stats_lock:
                self._stats["connections_reused"] += 1
            return conn
        except Empty:
            raise TimeoutError(
                f"Не удалось получить соединение за {self.timeout}s. "
                f"Увеличьте max_connections или timeout."
            )

    def _return_connection(self, conn: sqlite3.Connection):
        """
        Вернуть соединение в пул

        Args:
            conn: Соединение для возврата
        """
        if self._closed:
            # Если пул закрыт, закрываем соединение
            try:
                conn.close()
            except Exception:
                pass
            return

        try:
            # Проверяем, что соединение живое
            conn.execute("SELECT 1")
            # Возвращаем в пул
            self._pool.put_nowait(conn)
            logger.debug("Соединение возвращено в пул")
        except Exception as e:
            logger.warning(f"Соединение повреждено, закрываем: {e}")
            try:
                conn.close()
            except Exception:
                pass
            # Удаляем из списка всех соединений
            with self._lock:
                if conn in self._all_connections:
                    self._all_connections.remove(conn)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Контекстный менеджер для получения соединения

        Автоматически возвращает соединение в пул после использования.

        Yields:
            Соединение к SQLite БД

        Example:
            >>> with pool.get_connection() as conn:
            ...     cursor = conn.cursor()
            ...     cursor.execute("SELECT * FROM users")
        """
        conn = self._get_or_create_connection()

        with self._stats_lock:
            self._stats["active_connections"] += 1

        try:
            yield conn
            # Явный commit если не autocommit
            if conn.isolation_level is not None:
                conn.commit()
        except Exception:
            # Rollback при ошибке
            if conn.isolation_level is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            with self._stats_lock:
                self._stats["active_connections"] -= 1
            self._return_connection(conn)

    def get_stats(self) -> dict:
        """
        Получить статистику использования пула

        Returns:
            Словарь со статистикой:
            - connections_created: Всего создано соединений
            - connections_reused: Переиспользовано соединений из пула
            - pool_waits: Сколько раз пришлось ждать освобождения
            - active_connections: Текущее количество активных соединений
            - available_connections: Доступно соединений в пуле
            - total_connections: Всего соединений в пуле
        """
        with self._stats_lock:
            stats = self._stats.copy()

        stats["available_connections"] = self._pool.qsize()
        stats["total_connections"] = len(self._all_connections)

        return stats

    def close_all(self):
        """
        Закрыть все соединения в пуле

        Должно вызываться при завершении работы приложения.
        Идемпотентная операция (можно вызывать многократно).
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True

        # Закрываем все соединения
        closed_count = 0
        for conn in self._all_connections:
            try:
                conn.close()
                closed_count += 1
            except Exception as e:
                logger.warning(f"Ошибка при закрытии соединения: {e}")

        self._all_connections.clear()

        # Очищаем очередь
        while not self._pool.empty():
            try:
                self._pool.get_nowait()
            except Empty:
                break

        logger.info(f"Connection pool закрыт: закрыто {closed_count} соединений")

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.close_all()
        return False

    def __del__(self):
        """Cleanup on garbage collection"""
        try:
            self.close_all()
        except Exception:
            pass


def create_connection_pool(
    db_path: str,
    max_connections: int = ConnectionPool.DEFAULT_MAX_CONNECTIONS,
    **kwargs
) -> ConnectionPool:
    """
    Фабричная функция для создания пула соединений

    Args:
        db_path: Путь к файлу БД
        max_connections: Максимальное количество соединений
        **kwargs: Дополнительные параметры для ConnectionPool

    Returns:
        Настроенный пул соединений

    Example:
        >>> pool = create_connection_pool("data/bot.db", max_connections=5)
        >>> with pool.get_connection() as conn:
        ...     # работа с БД
        ...     pass
    """
    return ConnectionPool(db_path, max_connections=max_connections, **kwargs)


if __name__ == "__main__":
    # Демонстрация использования
    import tempfile
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Создаём временную БД для теста
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db = f.name

    print(f"Тестовая БД: {test_db}")

    # Создаём пул
    pool = create_connection_pool(test_db, max_connections=3)

    # Создаём тестовую таблицу
    with pool.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                value TEXT,
                thread_id TEXT
            )
        """)

    def worker(worker_id: int) -> str:
        """Тестовый воркер для параллельной работы"""
        try:
            with pool.get_connection() as conn:
                cursor = conn.cursor()

                # Вставка
                cursor.execute(
                    "INSERT INTO test (value, thread_id) VALUES (?, ?)",
                    (f"value_{worker_id}", str(threading.current_thread().ident))
                )

                # Чтение
                cursor.execute("SELECT COUNT(*) FROM test")
                count = cursor.fetchone()[0]

                # Небольшая задержка для имитации работы
                time.sleep(0.1)

                return f"Worker {worker_id}: вставил запись, всего записей: {count}"
        except Exception as e:
            return f"Worker {worker_id}: ошибка - {e}"

    # Параллельная работа с пулом
    print("\nЗапуск 10 параллельных воркеров...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]

        for future in as_completed(futures):
            print(future.result())

    # Статистика
    stats = pool.get_stats()
    print("\nСтатистика пула:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Проверка финальных данных
    with pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM test")
        total = cursor.fetchone()[0]
        print(f"\nВсего записей в БД: {total}")

    # Закрываем пул
    pool.close_all()
    print("Пул закрыт")

    # Удаляем тестовую БД
    Path(test_db).unlink(missing_ok=True)
    print(f"Тестовая БД удалена: {test_db}")
