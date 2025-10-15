#!/usr/bin/env python3
"""
Миграция embeddings из pickle в numpy формат

SECURITY FIX: Заменяем небезопасную pickle десериализацию на numpy.save/load

ВНИМАНИЕ: Запускайте только ОДИН РАЗ после обновления кода!
"""
import argparse
import io
import pickle
import sqlite3
import sys
from pathlib import Path

import numpy as np


def migrate_database(db_path: str, dry_run: bool = True):
    """
    Мигрирует embeddings из pickle в numpy формат

    Args:
        db_path: Путь к базе данных
        dry_run: Если True - только проверка, без изменений
    """
    if not Path(db_path).exists():
        print(f"❌ База данных не найдена: {db_path}")
        return False

    print(f"📂 Открываю базу: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Проверяем сколько embeddings есть
    cursor.execute("SELECT COUNT(*) FROM published WHERE embedding IS NOT NULL")
    total_count = cursor.fetchone()[0]

    if total_count == 0:
        print("✅ Нет embeddings для миграции")
        conn.close()
        return True

    print(f"📊 Найдено {total_count} embeddings для миграции")

    if dry_run:
        print("\n🔍 DRY RUN режим - изменения НЕ будут сохранены")
        print("   Запустите с --apply для реальной миграции\n")

    # Получаем все embeddings
    cursor.execute("SELECT id, embedding FROM published WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()

    migrated = 0
    errors = 0

    for row_id, embedding_bytes in rows:
        try:
            # Пытаемся десериализовать через pickle (ОПАСНО!)
            embedding = pickle.loads(embedding_bytes)

            # Проверяем что это numpy array
            if not isinstance(embedding, np.ndarray):
                print(f"⚠️  ID {row_id}: не numpy array, пропускаем")
                continue

            # Сериализуем через numpy (БЕЗОПАСНО!)
            buffer = io.BytesIO()
            np.save(buffer, embedding, allow_pickle=False)
            new_embedding_bytes = buffer.getvalue()

            if not dry_run:
                # Обновляем в БД
                cursor.execute(
                    "UPDATE published SET embedding = ? WHERE id = ?",
                    (new_embedding_bytes, row_id)
                )

            migrated += 1
            if migrated % 100 == 0:
                print(f"   Обработано: {migrated}/{total_count}")

        except Exception as e:
            print(f"❌ Ошибка при миграции ID {row_id}: {e}")
            errors += 1

    if not dry_run:
        conn.commit()
        print(f"\n💾 Изменения сохранены в базу")

    conn.close()

    print(f"\n✅ Миграция завершена:")
    print(f"   - Успешно: {migrated}")
    print(f"   - Ошибок: {errors}")

    if dry_run:
        print(f"\n⚠️  Для применения изменений запустите:")
        print(f"   python scripts/migrate_pickle_to_numpy.py --db {db_path} --apply")

    return errors == 0


def main():
    parser = argparse.ArgumentParser(
        description="Миграция embeddings из pickle в numpy формат (SECURITY FIX)"
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Путь к базе данных (например: ./data/marketplace_news.db)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить изменения (по умолчанию только dry-run)"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🔒 SECURITY MIGRATION: pickle → numpy")
    print("=" * 70)
    print()
    print("⚠️  ВАЖНО: Создайте бэкап базы перед запуском!")
    print(f"   cp {args.db} {args.db}.backup")
    print()

    if not args.apply:
        print("🔍 Запуск в DRY-RUN режиме (без изменений)")
    else:
        print("⚡ Запуск с применением изменений")
        response = input("\n❓ Вы создали бэкап? (yes/no): ")
        if response.lower() != "yes":
            print("❌ Миграция отменена. Создайте бэкап и запустите снова.")
            return 1

    print()

    success = migrate_database(args.db, dry_run=not args.apply)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
