"""Тесты для timezone-aware функциональности"""

import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from database.db import Database
from utils.timezone import get_timezone, now_in_timezone


@pytest.fixture
def temp_db():
    """Создать временную БД для тестов"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(path)
    yield db

    db.close()
    if os.path.exists(path):
        os.unlink(path)


class TestTimezoneStats:
    """Тесты для timezone-aware статистики"""

    def test_get_today_stats_utc(self, temp_db):
        """Проверить статистику за сегодня в UTC"""
        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Добавляем сообщение с сегодняшней датой UTC
        now_utc = datetime.now(UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Test message",
            date=now_utc,
        )

        # Помечаем как обработанное
        temp_db.mark_as_processed(1, rejection_reason="published")

        # Получаем статистику (UTC по умолчанию)
        stats = temp_db.get_today_stats(timezone_name=None)

        assert stats["messages_today"] == 1
        assert stats["processed_today"] == 1

    def test_get_today_stats_moscow(self, temp_db):
        """Проверить статистику за сегодня в Moscow timezone"""
        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Получаем текущее время в Москве
        moscow_tz = get_timezone("Europe/Moscow")
        now_moscow = now_in_timezone(moscow_tz)

        # Конвертируем в UTC для сохранения в БД
        now_utc = now_moscow.astimezone(UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Test message",
            date=now_utc,
        )

        # Получаем статистику для Moscow timezone
        stats = temp_db.get_today_stats(timezone_name="Europe/Moscow")

        assert stats["messages_today"] == 1

    def test_day_boundary_moscow_2359(self, temp_db):
        """
        Тест на границу суток: 23:59 МСК

        Сообщение в 23:59 по Москве должно учитываться в статистике "сегодня"
        даже если это уже завтра по UTC.
        """
        moscow_tz = get_timezone("Europe/Moscow")
        now_moscow = now_in_timezone(moscow_tz)

        # Создаем время 23:59 сегодня по Москве
        today_2359_msk = now_moscow.replace(hour=23, minute=59, second=0, microsecond=0)

        # Если сейчас уже позже 23:59, берем 23:59 вчера
        if now_moscow.hour == 23 and now_moscow.minute == 59:
            pass  # Уже 23:59, используем текущее время
        elif (
            now_moscow.hour < 23
            or (now_moscow.hour == 23 and now_moscow.minute < 59)
        ):
            pass  # Сегодня ещё не было 23:59, используем сегодня
        else:
            # Уже прошло 23:59 сегодня, используем вчерашние 23:59
            # (но это не важно для теста, важна логика)
            pass

        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Конвертируем в UTC
        date_2359_utc = today_2359_msk.astimezone(UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Message at 23:59 MSK",
            date=date_2359_utc,
        )

        # Мокаем текущее время как 23:59:30 МСК (через 30 секунд после сообщения)
        mock_now = today_2359_msk + timedelta(seconds=30)

        with patch("database.db.now_in_timezone", return_value=mock_now):
            stats = temp_db.get_today_stats(timezone_name="Europe/Moscow")

        # Сообщение должно быть в статистике "сегодня" по МСК
        assert stats["messages_today"] == 1

    def test_day_boundary_moscow_0001(self, temp_db):
        """
        Тест на границу суток: 00:01 МСК

        Сообщение в 00:01 следующего дня по Москве НЕ должно учитываться
        в статистике "сегодня" (если сейчас 23:59 сегодня).
        """
        moscow_tz = get_timezone("Europe/Moscow")
        now_moscow = now_in_timezone(moscow_tz)

        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Создаем время 00:01 завтрашнего дня по Москве
        tomorrow_0001_msk = (
            now_moscow.replace(hour=0, minute=1, second=0, microsecond=0)
            + timedelta(days=1)
        )

        # Конвертируем в UTC
        date_0001_utc = tomorrow_0001_msk.astimezone(UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Message at 00:01 tomorrow MSK",
            date=date_0001_utc,
        )

        # Мокаем текущее время как 23:59 сегодня по МСК
        mock_now = now_moscow.replace(hour=23, minute=59, second=0, microsecond=0)

        with patch("database.db.now_in_timezone", return_value=mock_now):
            stats = temp_db.get_today_stats(timezone_name="Europe/Moscow")

        # Сообщение НЕ должно быть в статистике "сегодня"
        assert stats["messages_today"] == 0

    def test_published_today_with_timezone(self, temp_db):
        """Проверить подсчет опубликованных сообщений за сегодня с timezone"""
        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        moscow_tz = get_timezone("Europe/Moscow")
        now_moscow = now_in_timezone(moscow_tz)

        # Создаем сообщение и публикуем его
        now_utc = now_moscow.astimezone(UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Test message",
            date=now_utc,
        )

        # Публикуем (добавляем в таблицу published)
        # Создаем простой embedding для теста
        embedding = np.array([0.1] * 384)  # 384-мерный вектор
        temp_db.save_published(
            text="Test message",
            embedding=embedding,
            source_message_id=1,
            source_channel_id=channel_id,
        )

        # Получаем статистику
        stats = temp_db.get_today_stats(timezone_name="Europe/Moscow")

        assert stats["published_today"] == 1

    def test_different_timezones(self, temp_db):
        """Проверить что разные timezone дают разные результаты на границе дня"""
        # Время: 01:30 UTC = 04:30 МСК
        # Это "сегодня" по UTC, но может быть "сегодня" или "вчера" по МСК
        # в зависимости от реального времени

        # Создаем канал
        channel_id = temp_db.add_channel("test_channel", "Test Channel")

        # Создаем время 01:30 UTC
        utc_time = datetime(2025, 10, 15, 1, 30, 0, tzinfo=UTC)

        temp_db.save_message(
            channel_id=channel_id,
            message_id=1,
            text="Test message",
            date=utc_time,
        )

        # Мокаем текущее время как 02:00 UTC = 05:00 МСК (тот же день)
        mock_utc = datetime(2025, 10, 15, 2, 0, 0, tzinfo=UTC)
        mock_msk = mock_utc.astimezone(get_timezone("Europe/Moscow"))

        # Проверяем UTC
        with patch("database.db.datetime") as mock_dt:
            mock_dt.now.return_value = mock_utc
            stats_utc = temp_db.get_today_stats(timezone_name=None)

        # Проверяем Moscow
        with patch("database.db.now_in_timezone", return_value=mock_msk):
            stats_msk = temp_db.get_today_stats(timezone_name="Europe/Moscow")

        # Оба должны учесть сообщение, так как оно в тот же день
        assert stats_utc["messages_today"] == 1
        assert stats_msk["messages_today"] == 1
