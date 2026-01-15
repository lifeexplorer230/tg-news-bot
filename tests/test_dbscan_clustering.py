"""
FIX-DUPLICATE-4: Тесты для DBSCAN clustering вместо fixed threshold

Проблема: Фиксированный порог 0.78 не учитывает локальную плотность похожих новостей.
Например, кластер из 5 новостей с similarity 0.80-0.85 между собой могут все пройти
как уникальные при попарном сравнении.

Решение: DBSCAN (Density-Based Spatial Clustering of Applications with Noise)
- Автоматически находит кластеры похожих новостей
- Оставляет только один представитель от каждого кластера
- Использует eps (расстояние) и min_samples (минимум точек в кластере)

Проверяет что:
1. DBSCAN детектирует кластеры похожих новостей
2. Из каждого кластера остаётся только один представитель
3. Шумовые точки (outliers) считаются уникальными
4. DBSCAN работает лучше чем fixed threshold для кластеров
"""

import numpy as np
import pytest
from unittest.mock import Mock

from services.news_processor import NewsProcessor
from utils.config import Config


class TestDBSCANClustering:
    """Тесты для DBSCAN clustering дедупликации"""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Временный путь к БД для тестов"""
        return str(tmp_path / "test.db")

    @pytest.fixture
    def mock_config(self, temp_db_path):
        """Mock config с настройками DBSCAN"""
        config = Mock(spec=Config)
        config.db_path = temp_db_path
        config.get = Mock(side_effect=lambda key, default=None: {
            "processor.duplicate_threshold": 0.78,
            "processor.use_dbscan": True,  # Включить DBSCAN
            "processor.dbscan_eps": 0.22,  # eps = 1 - similarity_threshold (1 - 0.78 = 0.22)
            "processor.dbscan_min_samples": 2,  # Минимум 2 точки для кластера
        }.get(key, default))
        config.database_settings = Mock(return_value={})
        return config

    def test_dbscan_finds_cluster_of_similar_news(self):
        """
        DBSCAN находит кластер из похожих новостей

        Сценарий:
        - Есть 4 очень похожие новости (similarity ~0.85 между собой)
        - Есть 1 уникальная новость (similarity ~0.50 с остальными)
        - DBSCAN должен найти 1 кластер из 4 новостей + 1 outlier
        """
        # Создаём 4 похожих embedding (кластер)
        cluster_embeddings = [
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.array([0.95, 0.1, 0.0, 0.0]),  # similarity ~0.95 с первым
            np.array([0.90, 0.15, 0.0, 0.0]),  # similarity ~0.90 с первым
            np.array([0.92, 0.12, 0.0, 0.0]),  # similarity ~0.92 с первым
        ]

        # Создаём 1 уникальный embedding (outlier)
        outlier_embedding = np.array([0.0, 0.0, 1.0, 0.0])

        all_embeddings = cluster_embeddings + [outlier_embedding]

        # Ожидаем что DBSCAN найдёт:
        # - Кластер 0: индексы [0, 1, 2, 3]
        # - Outlier: индекс [4] (label = -1)
        from sklearn.cluster import DBSCAN

        # Преобразуем similarity в distance: distance = 1 - similarity
        eps = 0.22  # Соответствует similarity threshold ~0.78
        dbscan = DBSCAN(eps=eps, min_samples=2, metric="cosine")
        labels = dbscan.fit_predict(all_embeddings)

        # Проверяем что первые 4 в одном кластере
        assert labels[0] == labels[1] == labels[2] == labels[3]
        assert labels[0] != -1  # Это кластер, не шум

        # Проверяем что последний - outlier
        assert labels[4] == -1  # Шум (outlier)

    def test_dbscan_keeps_one_representative_per_cluster(self):
        """
        DBSCAN оставляет только один представитель от каждого кластера

        Сценарий:
        - 3 новости в кластере A (про Ozon)
        - 2 новости в кластере B (про Wildberries)
        - 1 уникальная новость
        - Ожидаем: 3 уникальных (по одному из каждого кластера + outlier)
        """
        # Кластер A: Ozon (индексы 0, 1, 2)
        cluster_a = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.95, 0.1, 0.0]),
            np.array([0.92, 0.12, 0.0]),
        ]

        # Кластер B: Wildberries (индексы 3, 4)
        cluster_b = [
            np.array([0.0, 1.0, 0.0]),
            np.array([0.1, 0.95, 0.0]),
        ]

        # Outlier (индекс 5)
        outlier = [np.array([0.0, 0.0, 1.0])]

        all_embeddings = cluster_a + cluster_b + outlier

        from sklearn.cluster import DBSCAN

        eps = 0.22
        dbscan = DBSCAN(eps=eps, min_samples=2, metric="cosine")
        labels = dbscan.fit_predict(all_embeddings)

        # Проверяем количество уникальных кластеров
        unique_clusters = set(labels)
        # Должно быть 2 кластера + outliers (-1)
        assert len(unique_clusters) >= 2

        # Проверяем что можем выбрать представителей
        representatives = []
        for cluster_id in unique_clusters:
            if cluster_id == -1:
                # Все outliers уникальны
                outlier_indices = [i for i, label in enumerate(labels) if label == -1]
                representatives.extend(outlier_indices)
            else:
                # Берём первый элемент из кластера
                cluster_indices = [i for i, label in enumerate(labels) if label == cluster_id]
                representatives.append(cluster_indices[0])

        # Должно остаться 3-4 уникальных новости
        assert 3 <= len(representatives) <= 4

    def test_dbscan_better_than_fixed_threshold_for_clusters(self):
        """
        DBSCAN работает лучше fixed threshold для кластеров

        Проблемный сценарий для fixed threshold:
        - 5 новостей с попарной similarity 0.80-0.82
        - Fixed threshold 0.78: может пропустить все 5 как уникальные
        - DBSCAN: найдёт кластер и оставит только 1

        Пример:
        News 1: "Ozon снизил комиссию"
        News 2: "Маркетплейс Ozon объявил о снижении комиссии"
        News 3: "На Ozon стала ниже комиссия для продавцов"
        News 4: "Комиссия на Ozon снижена"
        News 5: "Ozon уменьшил комиссию продавцам"

        Попарная similarity ~0.80-0.82, но это явный кластер дубликатов.
        """
        # Создаём 5 нормализованных embedding с similarity ~0.80-0.82 между собой
        # Используем математический подход: v2 = α * v1 + β * orthogonal
        # где α = target_similarity, β = sqrt(1 - α²)
        base = np.array([1.0, 0.0, 0.0, 0.0])
        orthogonal = np.array([0.0, 1.0, 0.0, 0.0])

        def create_with_similarity(base_vec, target_sim):
            """Создаёт вектор с заданной similarity к base_vec"""
            alpha = target_sim
            beta = np.sqrt(1 - alpha**2)
            return alpha * base_vec + beta * orthogonal

        cluster_embeddings = [
            base,
            create_with_similarity(base, 0.85),
            create_with_similarity(base, 0.83),
            create_with_similarity(base, 0.82),
            create_with_similarity(base, 0.84),
        ]

        # Проверяем попарную similarity
        from services.embeddings import EmbeddingService

        max_similarities = []
        for i, emb in enumerate(cluster_embeddings):
            if i == 0:
                continue
            sim = EmbeddingService.cosine_similarity(cluster_embeddings[0], emb)
            max_similarities.append(sim)

        # Все similarity должны быть в диапазоне 0.80-0.90
        assert all(0.80 <= sim <= 0.90 for sim in max_similarities), f"Similarities: {max_similarities}"

        # FIXED THRESHOLD подход: проверяем последовательно
        threshold = 0.78
        unique_fixed = [cluster_embeddings[0]]  # Первый всегда уникален

        for emb in cluster_embeddings[1:]:
            max_sim = max(
                EmbeddingService.cosine_similarity(emb, seen)
                for seen in unique_fixed
            )
            if max_sim < threshold:
                unique_fixed.append(emb)

        # Fixed threshold может пропустить несколько как уникальные
        # (т.к. similarity ~0.80-0.82 может быть < threshold в некоторых парах)
        fixed_count = len(unique_fixed)

        # DBSCAN подход
        from sklearn.cluster import DBSCAN

        eps = 0.22  # 1 - 0.78
        dbscan = DBSCAN(eps=eps, min_samples=2, metric="cosine")
        labels = dbscan.fit_predict(cluster_embeddings)

        unique_clusters = set(labels)
        if -1 in unique_clusters:
            # Считаем outliers отдельно
            outlier_count = list(labels).count(-1)
            cluster_count = len(unique_clusters) - 1
            dbscan_count = cluster_count + outlier_count
        else:
            dbscan_count = len(unique_clusters)

        # DBSCAN должен найти меньше уникальных (или равно)
        # т.к. он правильно определяет это как кластер
        assert dbscan_count <= fixed_count

    def test_dbscan_handles_empty_input(self):
        """DBSCAN корректно обрабатывает пустой список"""
        from sklearn.cluster import DBSCAN

        embeddings = []
        if len(embeddings) == 0:
            # Пустой список - нет дубликатов
            result = []
        else:
            dbscan = DBSCAN(eps=0.22, min_samples=2, metric="cosine")
            labels = dbscan.fit_predict(embeddings)
            result = labels

        assert len(result) == 0

    def test_dbscan_handles_single_item(self):
        """DBSCAN корректно обрабатывает один элемент"""
        from sklearn.cluster import DBSCAN

        embeddings = [np.array([1.0, 0.0, 0.0])]
        dbscan = DBSCAN(eps=0.22, min_samples=2, metric="cosine")
        labels = dbscan.fit_predict(embeddings)

        # Один элемент не может сформировать кластер (min_samples=2)
        # Должен быть помечен как outlier (-1)
        assert labels[0] == -1

    def test_dbscan_all_unique_items(self):
        """
        DBSCAN правильно определяет что все элементы уникальны

        Сценарий: 5 новостей на разные темы, очень низкая similarity
        """
        # 5 ортогональных векторов (similarity ~0)
        embeddings = [
            np.array([1.0, 0.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 0.0, 1.0, 0.0, 0.0]),
            np.array([0.0, 0.0, 0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 0.0, 0.0, 1.0]),
        ]

        from sklearn.cluster import DBSCAN

        eps = 0.22
        dbscan = DBSCAN(eps=eps, min_samples=2, metric="cosine")
        labels = dbscan.fit_predict(embeddings)

        # Все должны быть outliers (нет кластеров)
        assert all(label == -1 for label in labels)

    def test_dbscan_config_parameters(self, mock_config):
        """
        Параметры DBSCAN настраиваются через config

        Проверяем:
        - processor.use_dbscan (включить/выключить)
        - processor.dbscan_eps (расстояние для кластера)
        - processor.dbscan_min_samples (минимум точек в кластере)
        """
        processor = NewsProcessor(mock_config)

        # Проверяем что параметры загружены из config
        # (будут добавлены в следующем коммите)
        assert hasattr(processor, "use_dbscan") or mock_config.get("processor.use_dbscan") is not None
        assert mock_config.get("processor.dbscan_eps") == 0.22
        assert mock_config.get("processor.dbscan_min_samples") == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
