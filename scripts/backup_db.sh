#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-${ROOT_DIR}/data/marketplace_news.db}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TARGET_FILE="${BACKUP_DIR}/marketplace_news_${TIMESTAMP}.db"

if [ ! -f "${DB_PATH}" ]; then
  echo "❌ Database not found at ${DB_PATH}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
cp "${DB_PATH}" "${TARGET_FILE}"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "${TARGET_FILE}" "PRAGMA integrity_check;" >/dev/null
fi

echo "✅ Backup created: ${TARGET_FILE}"
