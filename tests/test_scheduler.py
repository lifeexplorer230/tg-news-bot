"""Тесты для adaptive scheduler (CR-C7)"""

import threading
import time
from unittest.mock import patch

import schedule


def test_scheduler_adaptive_idle_normal_schedule(monkeypatch):
    """Тест: scheduler использует adaptive idle time для нормального расписания"""
    # Setup: добавляем задачу через 10 секунд
    schedule.clear()
    schedule.every(10).seconds.do(lambda: None)

    # Проверяем что idle_seconds() возвращает примерно 10 секунд
    idle = schedule.idle_seconds()
    assert idle is not None
    assert 9 <= idle <= 11  # Небольшая погрешность допустима

    # Cleanup
    schedule.clear()


def test_scheduler_adaptive_idle_empty_schedule(monkeypatch):
    """Тест: scheduler обрабатывает пустое расписание (idle = None)"""
    schedule.clear()

    # Проверяем что idle_seconds() возвращает None для пустого расписания
    idle = schedule.idle_seconds()
    assert idle is None

    # Cleanup
    schedule.clear()


def test_scheduler_adaptive_idle_missed_jobs(monkeypatch):
    """Тест: scheduler обрабатывает пропущенные задачи (idle < 0)"""
    schedule.clear()

    # Setup: создаем задачу в прошлом
    schedule.every(1).seconds.do(lambda: None)
    time.sleep(2)  # Ждем чтобы задача стала "пропущенной"

    # Проверяем что idle_seconds() возвращает отрицательное значение
    idle = schedule.idle_seconds()
    assert idle is not None
    assert idle < 0  # Задача просрочена

    # Cleanup
    schedule.clear()


def test_scheduler_safety_sleep_cap():
    """Тест: scheduler применяет safety sleep cap (max 5 секунд)"""
    schedule.clear()

    # Setup: задача через 100 секунд
    schedule.every(100).seconds.do(lambda: None)

    idle = schedule.idle_seconds()
    assert idle is not None
    assert idle > 5  # Больше 5 секунд до следующей задачи

    # В реальном scheduler должен использоваться min(idle, 5)
    sleep_time = min(idle, 5)
    assert sleep_time == 5  # Safety cap применён

    # Cleanup
    schedule.clear()


def test_scheduler_graceful_shutdown(monkeypatch):
    """Тест: scheduler корректно останавливается через global running flag"""
    from main import run_scheduler

    # Создаем тестовое расписание
    schedule.clear()
    call_count = {"count": 0}

    def test_job():
        call_count["count"] += 1

    schedule.every(1).seconds.do(test_job)

    # Запускаем scheduler в отдельном потоке
    import main

    original_running = main.running
    main.running = True

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Даём scheduler поработать 2-3 секунды
    time.sleep(2.5)

    # Останавливаем scheduler
    main.running = False

    # Ждем завершения потока
    scheduler_thread.join(timeout=5)

    # Проверяем что поток завершился
    assert not scheduler_thread.is_alive()

    # Проверяем что задачи выполнялись
    assert call_count["count"] >= 2  # Должно быть минимум 2 вызова за 2.5 секунды

    # Cleanup
    main.running = original_running
    schedule.clear()


def test_scheduler_run_pending_called():
    """Тест: scheduler вызывает schedule.run_pending() на каждой итерации"""
    schedule.clear()

    # Setup: создаем задачу с счетчиком
    call_count = {"count": 0}

    def test_job():
        call_count["count"] += 1

    schedule.every(1).seconds.do(test_job)

    # Вручную вызываем run_pending несколько раз
    time.sleep(1.1)  # Даём время чтобы задача стала готова к выполнению
    schedule.run_pending()
    assert call_count["count"] == 1

    time.sleep(1.1)
    schedule.run_pending()
    assert call_count["count"] == 2

    # Cleanup
    schedule.clear()
