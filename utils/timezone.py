"""Утилиты для работы с временными зонами"""

from datetime import UTC, datetime

import pytz

# Московское время (UTC+3)
MOSCOW_TZ = pytz.timezone("Europe/Moscow")


def now_msk() -> datetime:
    """
    Получить текущее время в московской timezone

    Returns:
        datetime с timezone Europe/Moscow
    """
    return datetime.now(MOSCOW_TZ)


def now_utc() -> datetime:
    """
    Получить текущее время в UTC

    Returns:
        datetime с timezone UTC
    """
    return datetime.now(UTC)


def to_msk(dt: datetime) -> datetime:
    """
    Конвертировать datetime в московское время

    Args:
        dt: datetime объект (может быть naive или aware)

    Returns:
        datetime в московской timezone
    """
    if dt.tzinfo is None:
        # Если naive datetime, считаем что это UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MOSCOW_TZ)


def to_utc(dt: datetime) -> datetime:
    """
    Конвертировать datetime в UTC

    Args:
        dt: datetime объект (может быть naive или aware)

    Returns:
        datetime в UTC timezone
    """
    if dt.tzinfo is None:
        # Если naive datetime, считаем что это московское время
        dt = MOSCOW_TZ.localize(dt)
    return dt.astimezone(UTC)


def format_msk(dt: datetime) -> str:
    """
    Форматировать datetime в строку в московском времени

    Args:
        dt: datetime объект

    Returns:
        Строка вида "2025-10-11 15:30:45 MSK"
    """
    msk_dt = to_msk(dt)
    return msk_dt.strftime("%Y-%m-%d %H:%M:%S MSK")


def get_timezone(tz_name: str):
    """
    Получить timezone объект по имени

    Args:
        tz_name: Имя timezone (например, 'Europe/Moscow')

    Returns:
        pytz.timezone объект
    """
    return pytz.timezone(tz_name)


def now_in_timezone(tz):
    """
    Получить текущее время в указанной timezone

    Args:
        tz: pytz.timezone объект

    Returns:
        datetime с указанной timezone
    """
    return datetime.now(tz)
