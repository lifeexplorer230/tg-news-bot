#!/usr/bin/env python3
"""
Миграция embeddings из pickle формата в безопасный numpy формат
Запускается один раз для конвертации старых данных
"""
import io
import os
import sqlite3
import sys

import numpy as np


def migrate_embeddings(db_path: str) -> None:
    """Мигрирует embeddings из pickle в безопасный формат"""
    print(f"Миграция embeddings в БД: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Получаем все записи с embeddings
    cursor.execute("SELECT id, embedding FROM published WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()

    print(f"Найдено записей с embeddings: {len(rows)}")

    migrated = 0
    errors = 0

    for row_id, embedding_bytes in rows:
        try:
            # Читаем старый формат с allow_pickle=True (только для миграции!)
            buffer = io.BytesIO(embedding_bytes)
            old_embedding = np.load(buffer, allow_pickle=True)

            # Проверяем что это валидный numpy array
            if not isinstance(old_embedding, np.ndarray):
                print(f"  [!] ID {row_id}: Не numpy array, пропускаем")
                errors += 1
                continue

            # Пересохраняем в безопасном формате (allow_pickle=False)
            new_buffer = io.BytesIO()
            np.save(new_buffer, old_embedding, allow_pickle=False)
            new_embedding_bytes = new_buffer.getvalue()

            # Обновляем запись
            cursor.execute(
                "UPDATE published SET embedding = ? WHERE id = ?",
                (new_embedding_bytes, row_id)
            )
            migrated += 1

            if migrated % 10 == 0:
                print(f"  Обработано: {migrated}/{len(rows)}")
                # Периодический commit для сохранения прогресса
                conn.commit()

        except Exception as e:
            print(f"  [!] Ошибка при миграции ID {row_id}: {e}")
            errors += 1
            # Не прерываем весь процесс, продолжаем с следующим

    # Финальный commit
    conn.commit()
    conn.close()

    print(f"\n✅ Миграция завершена:")
    print(f"  • Успешно: {migrated}")
    print(f"  • Ошибок: {errors}")
    print(f"  • Всего: {len(rows)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 migrate_embeddings.py <db_path>")
        sys.exit(1)

    db_path = sys.argv[1]

    # Проверяем существование БД
    if not os.path.exists(db_path):
        print(f"❌ Ошибка: БД не найдена: {db_path}")
        sys.exit(1)

    migrate_embeddings(db_path)
