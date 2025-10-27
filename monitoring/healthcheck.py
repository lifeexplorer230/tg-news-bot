"""
Health Check сервис для мониторинга состояния системы

Проверяет:
- Database health (подключение и производительность)
- Telegram API доступность
- Gemini API доступность
- Disk space и memory usage
- Heartbeat файлы для listener
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import google.generativeai as genai
from telethon import TelegramClient
from telethon.errors import RPCError

from database.db import Database
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class HealthStatus:
    """Статус компонента системы"""
    component: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class SystemHealth:
    """Общее состояние системы"""
    status: str  # "healthy", "degraded", "unhealthy"
    components: list[HealthStatus]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать в dict для JSON"""
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "components": [asdict(c) for c in self.components],
        }


class HealthChecker:
    """
    Сервис для проверки здоровья системы

    Features:
    - Проверка всех критичных компонентов
    - Измерение latency
    - JSON endpoint для мониторинга
    - Асинхронные проверки
    """

    # Пороги для disk space (в процентах)
    DISK_WARNING_THRESHOLD = 20.0  # < 20% свободно - warning
    DISK_CRITICAL_THRESHOLD = 10.0  # < 10% свободно - critical

    # Пороги для memory (в процентах)
    MEMORY_WARNING_THRESHOLD = 20.0
    MEMORY_CRITICAL_THRESHOLD = 10.0

    # Timeout для проверок (секунды)
    CHECK_TIMEOUT = 10.0

    def __init__(
        self,
        db_path: str | None = None,
        telegram_client: TelegramClient | None = None,
        gemini_api_key: str | None = None,
        heartbeat_path: str | None = None,
        heartbeat_max_age: int = 180,
    ):
        """
        Инициализация health checker

        Args:
            db_path: Путь к базе данных
            telegram_client: Telegram клиент (опционально)
            gemini_api_key: API ключ Gemini (опционально)
            heartbeat_path: Путь к heartbeat файлу listener (опционально)
            heartbeat_max_age: Максимальный возраст heartbeat в секундах
        """
        self.db_path = db_path
        self.telegram_client = telegram_client
        self.gemini_api_key = gemini_api_key
        self.heartbeat_path = heartbeat_path
        self.heartbeat_max_age = heartbeat_max_age

        logger.info("HealthChecker initialized")

    async def check_database(self) -> HealthStatus:
        """
        Проверить состояние базы данных

        Returns:
            HealthStatus для БД
        """
        if not self.db_path:
            return HealthStatus(
                component="database",
                status="unhealthy",
                message="Database path not configured",
            )

        start_time = time.time()

        try:
            # Проверяем существование файла БД
            if not Path(self.db_path).exists():
                return HealthStatus(
                    component="database",
                    status="unhealthy",
                    message="Database file does not exist",
                )

            # Пробуем подключиться и выполнить простой запрос
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()

            # Проверяем наличие основных таблиц
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('channels', 'raw_messages')"
            )
            tables = [row[0] for row in cursor.fetchall()]

            if len(tables) < 2:
                conn.close()
                return HealthStatus(
                    component="database",
                    status="degraded",
                    message="Missing required tables",
                    details={"tables_found": tables},
                )

            # Проверяем производительность (простой SELECT)
            cursor.execute("SELECT COUNT(*) FROM channels")
            channel_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            message_count = cursor.fetchone()[0]

            conn.close()

            latency_ms = (time.time() - start_time) * 1000

            return HealthStatus(
                component="database",
                status="healthy",
                message="Database operational",
                latency_ms=latency_ms,
                details={
                    "channels": channel_count,
                    "messages": message_count,
                    "path": self.db_path,
                },
            )

        except sqlite3.Error as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="database",
                status="unhealthy",
                message=f"Database error: {str(e)}",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="database",
                status="unhealthy",
                message=f"Unexpected error: {str(e)}",
                latency_ms=latency_ms,
            )

    async def check_telegram_api(self) -> HealthStatus:
        """
        Проверить доступность Telegram API

        Returns:
            HealthStatus для Telegram API
        """
        if not self.telegram_client:
            return HealthStatus(
                component="telegram_api",
                status="unhealthy",
                message="Telegram client not configured",
            )

        start_time = time.time()

        try:
            # Проверяем подключение
            if not self.telegram_client.is_connected():
                return HealthStatus(
                    component="telegram_api",
                    status="unhealthy",
                    message="Telegram client not connected",
                )

            # Пробуем получить информацию о себе (легкий запрос)
            me = await asyncio.wait_for(
                self.telegram_client.get_me(),
                timeout=self.CHECK_TIMEOUT,
            )

            latency_ms = (time.time() - start_time) * 1000

            return HealthStatus(
                component="telegram_api",
                status="healthy",
                message="Telegram API operational",
                latency_ms=latency_ms,
                details={
                    "user_id": me.id if me else None,
                    "username": me.username if me else None,
                },
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="telegram_api",
                status="degraded",
                message="Telegram API timeout",
                latency_ms=latency_ms,
            )

        except RPCError as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="telegram_api",
                status="unhealthy",
                message=f"Telegram RPC error: {str(e)}",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="telegram_api",
                status="unhealthy",
                message=f"Unexpected error: {str(e)}",
                latency_ms=latency_ms,
            )

    async def check_gemini_api(self) -> HealthStatus:
        """
        Проверить доступность Gemini API

        Returns:
            HealthStatus для Gemini API
        """
        if not self.gemini_api_key:
            return HealthStatus(
                component="gemini_api",
                status="unhealthy",
                message="Gemini API key not configured",
            )

        start_time = time.time()

        try:
            # Конфигурируем API
            genai.configure(api_key=self.gemini_api_key)

            # Пробуем получить список моделей (легкий запрос)
            models = await asyncio.wait_for(
                asyncio.to_thread(lambda: list(genai.list_models())),
                timeout=self.CHECK_TIMEOUT,
            )

            latency_ms = (time.time() - start_time) * 1000

            return HealthStatus(
                component="gemini_api",
                status="healthy",
                message="Gemini API operational",
                latency_ms=latency_ms,
                details={
                    "models_available": len(models),
                },
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="gemini_api",
                status="degraded",
                message="Gemini API timeout",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                component="gemini_api",
                status="unhealthy",
                message=f"Gemini API error: {str(e)}",
                latency_ms=latency_ms,
            )

    async def check_disk_space(self) -> HealthStatus:
        """
        Проверить доступное место на диске

        Returns:
            HealthStatus для disk space
        """
        try:
            # Получаем путь к корневой директории проекта
            project_root = Path.cwd()
            stat = shutil.disk_usage(project_root)

            total_gb = stat.total / (1024 ** 3)
            used_gb = stat.used / (1024 ** 3)
            free_gb = stat.free / (1024 ** 3)
            free_percent = (stat.free / stat.total) * 100

            # Определяем статус
            if free_percent < self.DISK_CRITICAL_THRESHOLD:
                status = "unhealthy"
                message = f"Critical: Only {free_percent:.1f}% disk space free"
            elif free_percent < self.DISK_WARNING_THRESHOLD:
                status = "degraded"
                message = f"Warning: Only {free_percent:.1f}% disk space free"
            else:
                status = "healthy"
                message = f"Disk space: {free_percent:.1f}% free"

            return HealthStatus(
                component="disk_space",
                status=status,
                message=message,
                details={
                    "total_gb": round(total_gb, 2),
                    "used_gb": round(used_gb, 2),
                    "free_gb": round(free_gb, 2),
                    "free_percent": round(free_percent, 2),
                    "path": str(project_root),
                },
            )

        except Exception as e:
            return HealthStatus(
                component="disk_space",
                status="unhealthy",
                message=f"Failed to check disk space: {str(e)}",
            )

    async def check_memory(self) -> HealthStatus:
        """
        Проверить использование памяти

        Returns:
            HealthStatus для memory
        """
        try:
            # Читаем /proc/meminfo (Linux)
            if not Path("/proc/meminfo").exists():
                return HealthStatus(
                    component="memory",
                    status="healthy",
                    message="Memory check not available on this platform",
                )

            with open("/proc/meminfo") as f:
                meminfo = f.read()

            # Парсим значения
            mem_total = None
            mem_available = None

            for line in meminfo.split("\n"):
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024  # KB to bytes
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024

            if mem_total is None or mem_available is None:
                return HealthStatus(
                    component="memory",
                    status="degraded",
                    message="Could not parse memory info",
                )

            mem_used = mem_total - mem_available
            mem_free_percent = (mem_available / mem_total) * 100

            total_gb = mem_total / (1024 ** 3)
            used_gb = mem_used / (1024 ** 3)
            available_gb = mem_available / (1024 ** 3)

            # Определяем статус
            if mem_free_percent < self.MEMORY_CRITICAL_THRESHOLD:
                status = "unhealthy"
                message = f"Critical: Only {mem_free_percent:.1f}% memory free"
            elif mem_free_percent < self.MEMORY_WARNING_THRESHOLD:
                status = "degraded"
                message = f"Warning: Only {mem_free_percent:.1f}% memory free"
            else:
                status = "healthy"
                message = f"Memory: {mem_free_percent:.1f}% free"

            return HealthStatus(
                component="memory",
                status=status,
                message=message,
                details={
                    "total_gb": round(total_gb, 2),
                    "used_gb": round(used_gb, 2),
                    "available_gb": round(available_gb, 2),
                    "free_percent": round(mem_free_percent, 2),
                },
            )

        except Exception as e:
            return HealthStatus(
                component="memory",
                status="degraded",
                message=f"Failed to check memory: {str(e)}",
            )

    async def check_listener_heartbeat(self) -> HealthStatus:
        """
        Проверить heartbeat listener

        Returns:
            HealthStatus для listener
        """
        if not self.heartbeat_path:
            return HealthStatus(
                component="listener_heartbeat",
                status="healthy",
                message="Heartbeat check not configured",
            )

        try:
            heartbeat_file = Path(self.heartbeat_path)

            if not heartbeat_file.exists():
                return HealthStatus(
                    component="listener_heartbeat",
                    status="unhealthy",
                    message="Heartbeat file does not exist",
                    details={"path": self.heartbeat_path},
                )

            # Читаем время последнего обновления
            mtime = heartbeat_file.stat().st_mtime
            age_seconds = time.time() - mtime

            if age_seconds > self.heartbeat_max_age:
                return HealthStatus(
                    component="listener_heartbeat",
                    status="unhealthy",
                    message=f"Listener heartbeat too old ({age_seconds:.0f}s)",
                    details={
                        "age_seconds": round(age_seconds, 2),
                        "max_age_seconds": self.heartbeat_max_age,
                        "path": self.heartbeat_path,
                    },
                )

            return HealthStatus(
                component="listener_heartbeat",
                status="healthy",
                message=f"Listener active (last heartbeat {age_seconds:.0f}s ago)",
                details={
                    "age_seconds": round(age_seconds, 2),
                    "max_age_seconds": self.heartbeat_max_age,
                    "path": self.heartbeat_path,
                },
            )

        except Exception as e:
            return HealthStatus(
                component="listener_heartbeat",
                status="unhealthy",
                message=f"Failed to check heartbeat: {str(e)}",
            )

    async def check_all(self) -> SystemHealth:
        """
        Выполнить все проверки

        Returns:
            SystemHealth с результатами всех проверок
        """
        logger.info("Running health checks...")

        # Запускаем все проверки параллельно
        checks = await asyncio.gather(
            self.check_database(),
            self.check_telegram_api(),
            self.check_gemini_api(),
            self.check_disk_space(),
            self.check_memory(),
            self.check_listener_heartbeat(),
            return_exceptions=True,
        )

        # Обрабатываем результаты
        components = []
        for check in checks:
            if isinstance(check, Exception):
                logger.error(f"Health check failed with exception: {check}")
                components.append(
                    HealthStatus(
                        component="unknown",
                        status="unhealthy",
                        message=f"Check failed: {str(check)}",
                    )
                )
            else:
                components.append(check)

        # Определяем общий статус
        statuses = [c.status for c in components]

        if all(s == "healthy" for s in statuses):
            overall_status = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall_status = "unhealthy"
        else:
            overall_status = "degraded"

        health = SystemHealth(
            status=overall_status,
            components=components,
        )

        logger.info(f"Health check completed: {overall_status}")
        return health


__all__ = [
    "HealthStatus",
    "SystemHealth",
    "HealthChecker",
]
