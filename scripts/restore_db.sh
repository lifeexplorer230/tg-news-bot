#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: restore_db.sh <path-to-backup>" >&2
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "${BACKUP_FILE}" ]; then
  echo "❌ Backup not found: ${BACKUP_FILE}" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${DB_PATH:-${ROOT_DIR}/data/marketplace_news.db}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "${BACKUP_DIR}"

if [ -f "${DB_PATH}" ]; then
  SAFETY_COPY="${BACKUP_DIR}/marketplace_news_pre_restore_${TIMESTAMP}.db"
  cp "${DB_PATH}" "${SAFETY_COPY}"
  echo "ℹ️  Existing database saved to ${SAFETY_COPY}"
fi

cp "${BACKUP_FILE}" "${DB_PATH}"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "${DB_PATH}" "PRAGMA integrity_check;" >/dev/null
fi

echo "✅ Database restored to ${DB_PATH}"
