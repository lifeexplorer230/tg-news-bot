"""
Система сбора метрик для мониторинга

Поддерживает:
- Счетчики (counters)
- Таймеры (timers/histograms)
- Gauges (текущее значение)
- Labels для группировки метрик
- Экспорт в Prometheus формате
- Контекстные менеджеры для удобного измерения времени
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Generator

from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class MetricValue:
    """Значение метрики"""
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class CounterMetric:
    """Счетчик - монотонно растущее значение"""
    name: str
    help_text: str
    values: dict[frozenset, float] = field(default_factory=lambda: defaultdict(float))

    def inc(self, labels: dict[str, str] | None = None, value: float = 1.0):
        """Увеличить счетчик"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        self.values[label_key] += value

    def get(self, labels: dict[str, str] | None = None) -> float:
        """Получить значение счетчика"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        return self.values.get(label_key, 0.0)


@dataclass
class GaugeMetric:
    """Gauge - текущее значение, может увеличиваться и уменьшаться"""
    name: str
    help_text: str
    values: dict[frozenset, float] = field(default_factory=lambda: defaultdict(float))

    def set(self, value: float, labels: dict[str, str] | None = None):
        """Установить значение gauge"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        self.values[label_key] = value

    def inc(self, labels: dict[str, str] | None = None, value: float = 1.0):
        """Увеличить gauge"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        self.values[label_key] += value

    def dec(self, labels: dict[str, str] | None = None, value: float = 1.0):
        """Уменьшить gauge"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        self.values[label_key] -= value

    def get(self, labels: dict[str, str] | None = None) -> float:
        """Получить значение gauge"""
        labels = labels or {}
        label_key = frozenset(labels.items())
        return self.values.get(label_key, 0.0)


@dataclass
class HistogramMetric:
    """Histogram - распределение значений (для таймеров)"""
    name: str
    help_text: str
    buckets: list[float]
    # Для каждого набора labels храним: (сумма, количество, bucket_counts)
    values: dict[frozenset, tuple[float, int, dict[float, int]]] = field(
        default_factory=lambda: defaultdict(lambda: (0.0, 0, defaultdict(int)))
    )

    def observe(self, value: float, labels: dict[str, str] | None = None):
        """Добавить наблюдение"""
        labels = labels or {}
        label_key = frozenset(labels.items())

        total_sum, count, bucket_counts = self.values[label_key]
        total_sum += value
        count += 1

        # Увеличиваем счетчики buckets
        for bucket in self.buckets:
            if value <= bucket:
                bucket_counts[bucket] += 1

        self.values[label_key] = (total_sum, count, bucket_counts)

    def get_stats(self, labels: dict[str, str] | None = None) -> dict[str, Any]:
        """Получить статистику"""
        labels = labels or {}
        label_key = frozenset(labels.items())

        if label_key not in self.values:
            return {"sum": 0.0, "count": 0, "avg": 0.0}

        total_sum, count, _ = self.values[label_key]
        avg = total_sum / count if count > 0 else 0.0

        return {
            "sum": total_sum,
            "count": count,
            "avg": avg,
        }


class MetricsCollector:
    """
    Коллектор метрик с поддержкой Prometheus формата

    Features:
    - Thread-safe операции
    - Поддержка counters, gauges, histograms
    - Labels для группировки
    - Экспорт в Prometheus формат
    - Context managers для таймеров
    """

    # Стандартные buckets для таймеров (в секундах)
    DEFAULT_TIMER_BUCKETS = [
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0
    ]

    def __init__(self):
        """Инициализация коллектора"""
        self._counters: dict[str, CounterMetric] = {}
        self._gauges: dict[str, GaugeMetric] = {}
        self._histograms: dict[str, HistogramMetric] = {}
        self._lock = Lock()

        logger.info("MetricsCollector initialized")

    def counter(self, name: str, help_text: str = "") -> CounterMetric:
        """
        Получить или создать counter метрику

        Args:
            name: Имя метрики
            help_text: Описание метрики

        Returns:
            Counter метрика
        """
        with self._lock:
            if name not in self._counters:
                self._counters[name] = CounterMetric(name, help_text)
            return self._counters[name]

    def gauge(self, name: str, help_text: str = "") -> GaugeMetric:
        """
        Получить или создать gauge метрику

        Args:
            name: Имя метрики
            help_text: Описание метрики

        Returns:
            Gauge метрика
        """
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = GaugeMetric(name, help_text)
            return self._gauges[name]

    def histogram(
        self,
        name: str,
        help_text: str = "",
        buckets: list[float] | None = None,
    ) -> HistogramMetric:
        """
        Получить или создать histogram метрику

        Args:
            name: Имя метрики
            help_text: Описание метрики
            buckets: Buckets для histogram (по умолчанию DEFAULT_TIMER_BUCKETS)

        Returns:
            Histogram метрика
        """
        with self._lock:
            if name not in self._histograms:
                buckets = buckets or self.DEFAULT_TIMER_BUCKETS
                self._histograms[name] = HistogramMetric(name, help_text, buckets)
            return self._histograms[name]

    @contextmanager
    def timer(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        help_text: str = "",
    ) -> Generator[None, None, None]:
        """
        Context manager для измерения времени выполнения

        Args:
            name: Имя метрики
            labels: Labels для группировки
            help_text: Описание метрики

        Example:
            with metrics.timer("api_call", {"endpoint": "/users"}):
                response = api.get_users()
        """
        histogram = self.histogram(name, help_text)
        start_time = time.time()

        try:
            yield
        finally:
            duration = time.time() - start_time
            histogram.observe(duration, labels)

    def inc_counter(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0):
        """
        Увеличить counter (shortcut)

        Args:
            name: Имя метрики
            labels: Labels
            value: На сколько увеличить
        """
        counter = self.counter(name)
        counter.inc(labels, value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """
        Установить gauge значение (shortcut)

        Args:
            name: Имя метрики
            value: Новое значение
            labels: Labels
        """
        gauge = self.gauge(name)
        gauge.set(value, labels)

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ):
        """
        Добавить наблюдение в histogram (shortcut)

        Args:
            name: Имя метрики
            value: Значение
            labels: Labels
        """
        histogram = self.histogram(name)
        histogram.observe(value, labels)

    def _format_labels(self, labels: frozenset) -> str:
        """Форматировать labels для Prometheus"""
        if not labels:
            return ""

        label_pairs = [f'{k}="{v}"' for k, v in sorted(labels)]
        return "{" + ",".join(label_pairs) + "}"

    def export_prometheus(self) -> str:
        """
        Экспортировать метрики в Prometheus формате

        Returns:
            Строка с метриками в Prometheus формате
        """
        lines = []

        with self._lock:
            # Counters
            for counter in self._counters.values():
                if counter.help_text:
                    lines.append(f"# HELP {counter.name} {counter.help_text}")
                lines.append(f"# TYPE {counter.name} counter")

                for label_key, value in counter.values.items():
                    labels_str = self._format_labels(label_key)
                    lines.append(f"{counter.name}{labels_str} {value}")

            # Gauges
            for gauge in self._gauges.values():
                if gauge.help_text:
                    lines.append(f"# HELP {gauge.name} {gauge.help_text}")
                lines.append(f"# TYPE {gauge.name} gauge")

                for label_key, value in gauge.values.items():
                    labels_str = self._format_labels(label_key)
                    lines.append(f"{gauge.name}{labels_str} {value}")

            # Histograms
            for histogram in self._histograms.values():
                if histogram.help_text:
                    lines.append(f"# HELP {histogram.name} {histogram.help_text}")
                lines.append(f"# TYPE {histogram.name} histogram")

                for label_key, (total_sum, count, bucket_counts) in histogram.values.items():
                    base_labels = dict(label_key)

                    # Buckets
                    for bucket in histogram.buckets:
                        bucket_labels = {**base_labels, "le": str(bucket)}
                        bucket_labels_str = self._format_labels(
                            frozenset(bucket_labels.items())
                        )
                        bucket_count = bucket_counts.get(bucket, 0)
                        lines.append(f"{histogram.name}_bucket{bucket_labels_str} {bucket_count}")

                    # +Inf bucket
                    inf_labels = {**base_labels, "le": "+Inf"}
                    inf_labels_str = self._format_labels(frozenset(inf_labels.items()))
                    lines.append(f"{histogram.name}_bucket{inf_labels_str} {count}")

                    # Sum
                    labels_str = self._format_labels(label_key)
                    lines.append(f"{histogram.name}_sum{labels_str} {total_sum}")

                    # Count
                    lines.append(f"{histogram.name}_count{labels_str} {count}")

        return "\n".join(lines) + "\n"

    def get_summary(self) -> dict[str, Any]:
        """
        Получить краткую сводку метрик

        Returns:
            Словарь с основными метриками
        """
        summary = {
            "counters": {},
            "gauges": {},
            "histograms": {},
        }

        with self._lock:
            # Counters
            for name, counter in self._counters.items():
                total = sum(counter.values.values())
                summary["counters"][name] = total

            # Gauges
            for name, gauge in self._gauges.items():
                # Для gauges берем последнее значение без labels
                if gauge.values:
                    # Если есть labels, берем сумму всех значений
                    total = sum(gauge.values.values())
                    summary["gauges"][name] = total
                else:
                    summary["gauges"][name] = 0.0

            # Histograms
            for name, histogram in self._histograms.items():
                total_sum = 0.0
                total_count = 0

                for _, (s, c, _) in histogram.values.items():
                    total_sum += s
                    total_count += c

                avg = total_sum / total_count if total_count > 0 else 0.0
                summary["histograms"][name] = {
                    "sum": total_sum,
                    "count": total_count,
                    "avg": avg,
                }

        return summary

    def reset(self):
        """Сбросить все метрики (для тестов)"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
        logger.info("All metrics reset")


# Глобальный экземпляр (singleton)
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """
    Получить глобальный MetricsCollector

    Returns:
        MetricsCollector (создается при первом вызове)
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Shortcuts для удобства
def counter(name: str, help_text: str = "") -> CounterMetric:
    """Получить counter метрику"""
    return get_metrics_collector().counter(name, help_text)


def gauge(name: str, help_text: str = "") -> GaugeMetric:
    """Получить gauge метрику"""
    return get_metrics_collector().gauge(name, help_text)


def histogram(name: str, help_text: str = "", buckets: list[float] | None = None) -> HistogramMetric:
    """Получить histogram метрику"""
    return get_metrics_collector().histogram(name, help_text, buckets)


def timer(name: str, labels: dict[str, str] | None = None, help_text: str = ""):
    """Context manager для таймера"""
    return get_metrics_collector().timer(name, labels, help_text)


__all__ = [
    "MetricValue",
    "CounterMetric",
    "GaugeMetric",
    "HistogramMetric",
    "MetricsCollector",
    "get_metrics_collector",
    "counter",
    "gauge",
    "histogram",
    "timer",
]
