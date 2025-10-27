"""
Пример полной интеграции модулей оптимизации производительности

Демонстрирует использование всех трёх модулей:
- Connection Pool
- Gemini Cache
- Batch Processor
"""

import time
from pathlib import Path

from database.connection_pool import ConnectionPool, create_connection_pool
from services.batch_processor import BatchItem, BatchProcessor, create_batch_processor
from services.gemini_cache import GeminiCache, create_gemini_cache


class OptimizedDatabase:
    """Database класс с connection pooling"""

    def __init__(self, db_path: str, max_connections: int = 5):
        self.pool = create_connection_pool(
            db_path, max_connections=max_connections, timeout=30.0
        )
        self._init_schema()

    def _init_schema(self):
        """Инициализация схемы БД"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    processed BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()

    def add_message(self, text: str) -> int:
        """Добавить сообщение"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO messages (text) VALUES (?)", (text,))
            conn.commit()
            return cursor.lastrowid

    def get_unprocessed(self) -> list[dict]:
        """Получить необработанные сообщения"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, text FROM messages WHERE processed = 0")
            return [{"id": row[0], "text": row[1]} for row in cursor.fetchall()]

    def mark_processed_batch(self, message_ids: list[int]):
        """Батчевая пометка как обработанные"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "UPDATE messages SET processed = 1 WHERE id = ?",
                [(msg_id,) for msg_id in message_ids],
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Статистика БД"""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM messages")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM messages WHERE processed = 1")
            processed = cursor.fetchone()[0]

            return {
                "total_messages": total,
                "processed": processed,
                "unprocessed": total - processed,
                "pool_stats": self.pool.get_stats(),
            }

    def close(self):
        """Закрыть пул"""
        self.pool.close_all()


class MockGeminiClient:
    """Мок Gemini клиента для демонстрации"""

    def __init__(self):
        self.call_count = 0

    def analyze_message(self, text: str) -> dict:
        """Имитация анализа через Gemini"""
        self.call_count += 1
        time.sleep(0.1)  # Имитация задержки API
        return {
            "score": len(text) % 10,
            "category": "news" if len(text) > 50 else "spam",
            "summary": text[:50] + "...",
        }


class CachedGeminiClient:
    """Gemini клиент с кэшированием"""

    def __init__(self, cache_size: int = 1000, ttl_hours: float = 24):
        self.client = MockGeminiClient()
        self.cache = create_gemini_cache(max_size=cache_size, ttl_hours=ttl_hours)

    def analyze_message(self, text: str) -> dict:
        """Анализ с кэшированием"""
        # Проверяем кэш
        cached = self.cache.get(text)
        if cached is not None:
            return cached

        # Вызываем API
        result = self.client.analyze_message(text)

        # Сохраняем в кэш
        self.cache.set(text, result)

        return result

    def get_stats(self) -> dict:
        """Статистика кэша и API"""
        return {
            "api_calls": self.client.call_count,
            "cache_stats": self.cache.get_stats(),
        }


class OptimizedMessageProcessor:
    """Оптимизированный процессор сообщений"""

    def __init__(
        self,
        db_path: str,
        batch_size: int = 100,
        batch_wait: float = 5.0,
        db_connections: int = 5,
        cache_size: int = 1000,
    ):
        # 1. Database с connection pool
        self.db = OptimizedDatabase(db_path, max_connections=db_connections)

        # 2. Gemini с кэшем
        self.gemini = CachedGeminiClient(cache_size=cache_size, ttl_hours=24)

        # 3. Batch processor для БД операций
        self.batch_processor = create_batch_processor(
            self._process_batch,
            max_batch_size=batch_size,
            max_wait_seconds=batch_wait,
        )
        self.batch_processor.start()

        # Счётчики
        self.processed_count = 0

    def _process_batch(self, items: list[BatchItem]):
        """Обработка батча сообщений"""
        message_ids = [item.data["message_id"] for item in items]

        # Батчевое обновление БД
        self.db.mark_processed_batch(message_ids)

        self.processed_count += len(items)
        print(f"  Batch processed: {len(items)} messages")

    def add_messages(self, texts: list[str]):
        """Добавить сообщения для обработки"""
        for text in texts:
            msg_id = self.db.add_message(text)
            print(f"Added message {msg_id}: {text[:30]}...")

    def process_all(self):
        """Обработать все необработанные сообщения"""
        messages = self.db.get_unprocessed()
        print(f"\nProcessing {len(messages)} messages...")

        for msg in messages:
            # Анализируем через Gemini (с кэшем)
            analysis = self.gemini.analyze_message(msg["text"])

            # Добавляем в батч для пометки
            self.batch_processor.add_item(
                data={"message_id": msg["id"], "analysis": analysis},
                metadata={"score": analysis["score"]},
            )

    def get_stats(self) -> dict:
        """Полная статистика"""
        return {
            "processor": {
                "processed_count": self.processed_count,
                "batch_stats": self.batch_processor.get_stats(),
            },
            "database": self.db.get_stats(),
            "gemini": self.gemini.get_stats(),
        }

    def shutdown(self):
        """Graceful shutdown"""
        print("\nShutting down...")
        self.batch_processor.shutdown(timeout=30.0)
        self.db.close()


def print_stats(stats: dict, title: str = "Statistics"):
    """Красивый вывод статистики"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

    def _print_dict(d: dict, indent: int = 0):
        for key, value in d.items():
            if isinstance(value, dict):
                print(f"{'  ' * indent}{key}:")
                _print_dict(value, indent + 1)
            else:
                if isinstance(value, float):
                    if 0 < value < 1:
                        print(f"{'  ' * indent}{key}: {value:.1%}")
                    else:
                        print(f"{'  ' * indent}{key}: {value:.2f}")
                else:
                    print(f"{'  ' * indent}{key}: {value}")

    _print_dict(stats)
    print(f"{'=' * 60}\n")


def main():
    """Демонстрация оптимизированного процессора"""

    # Создаём временную БД
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    print(f"Demo Database: {db_path}")
    print("=" * 60)

    # Создаём процессор с оптимизациями
    processor = OptimizedMessageProcessor(
        db_path=db_path,
        batch_size=10,  # Батч из 10 для демо
        batch_wait=2.0,  # Ждём 2 секунды
        db_connections=3,  # 3 соединения в пуле
        cache_size=100,  # 100 записей в кэше
    )

    # Тест 1: Добавление сообщений
    print("\n[TEST 1] Добавление сообщений...")
    test_messages = [
        "Breaking news: Major update in marketplace regulations affecting sellers",
        "New Wildberries commission structure announced for 2025",
        "Ozon introduces seller support program with subsidies",
        "Breaking news: Major update in marketplace regulations affecting sellers",  # Дубликат
        "Market analysis shows growing demand in electronics category",
        "Tips for optimizing product cards on e-commerce platforms",
        "New Wildberries commission structure announced for 2025",  # Дубликат
        "Government announces new logistics support for online sellers",
        "Quick tricks to boost your sales this month!",  # Спам
        "ВАЖНО: Изменения в законодательстве для селлеров маркетплейсов",
    ]
    processor.add_messages(test_messages)

    # Тест 2: Обработка (первый проход)
    print("\n[TEST 2] Первая обработка (без кэша)...")
    start_time = time.time()
    processor.process_all()
    time.sleep(3)  # Ждём обработки батча
    duration1 = time.time() - start_time

    stats1 = processor.get_stats()
    print_stats(stats1, "Статистика после первой обработки")

    # Тест 3: Добавление новых + дубликатов
    print("\n[TEST 3] Добавление новых сообщений с дубликатами...")
    more_messages = [
        "Breaking news: Major update in marketplace regulations affecting sellers",  # Дубликат
        "Flash sale strategies that actually work in 2025",
        "New Wildberries commission structure announced for 2025",  # Дубликат
        "Updated return policy guidelines from Ozon marketplace",
        "Market analysis shows growing demand in electronics category",  # Дубликат
    ]
    processor.add_messages(more_messages)

    # Тест 4: Обработка (с кэшем)
    print("\n[TEST 4] Вторая обработка (с использованием кэша)...")
    start_time = time.time()
    processor.process_all()
    time.sleep(3)  # Ждём обработки батча
    duration2 = time.time() - start_time

    stats2 = processor.get_stats()
    print_stats(stats2, "Статистика после второй обработки")

    # Тест 5: Сравнение производительности
    print("\n[TEST 5] Анализ производительности...")
    print(f"{'Метрика':<40} {'Значение':>15}")
    print("-" * 60)

    api_calls = stats2["gemini"]["api_calls"]
    total_processed = stats2["processor"]["processed_count"]
    cache_hit_rate = stats2["gemini"]["cache_stats"]["hit_rate"]

    print(f"{'Всего обработано сообщений':<40} {total_processed:>15}")
    print(f"{'Всего API вызовов':<40} {api_calls:>15}")
    print(f"{'Cache hit rate':<40} {cache_hit_rate:>14.1%}")
    print(f"{'Экономия API вызовов':<40} {total_processed - api_calls:>15}")
    print()
    print(f"{'Время первой обработки (без кэша)':<40} {duration1:>13.2f}s")
    print(f"{'Время второй обработки (с кэшем)':<40} {duration2:>13.2f}s")
    print(
        f"{'Ускорение от кэша':<40} {duration1/duration2 if duration2 > 0 else 0:>14.1f}x"
    )
    print()

    pool_stats = stats2["database"]["pool_stats"]
    print(f"{'Connection pool reuse rate':<40} "
          f"{pool_stats['connections_reused'] / max(1, pool_stats['connections_created'] + pool_stats['connections_reused']):.1%}:>15")
    print(f"{'Pool waits':<40} {pool_stats['pool_waits']:>15}")
    print()

    batch_stats = stats2["processor"]["batch_stats"]
    print(f"{'Батчей обработано':<40} {batch_stats['batches_processed']:>15}")
    print(f"{'Средний размер батча':<40} {batch_stats['avg_batch_size']:>14.1f}")
    print(
        f"{'Пропускная способность':<40} {batch_stats['throughput']:>13.1f}/s"
    )

    # Graceful shutdown
    processor.shutdown()

    # Удаляем тестовую БД
    Path(db_path).unlink(missing_ok=True)
    print(f"\nDemo completed. Database removed: {db_path}")


if __name__ == "__main__":
    main()
