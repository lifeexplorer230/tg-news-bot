"""Тесты для core/container.py"""

from unittest.mock import MagicMock

import pytest

from core.container import ServiceContainer, get_container, reset_container, set_container


class FakeConfig:
    """Mock Config для тестов"""

    def __init__(self):
        self.db_path = ":memory:"
        self.log_level = "INFO"

    def database_settings(self):
        return {"timeout": 30}


class FakeDatabase:
    """Mock Database для тестов"""

    def __init__(self, db_path, **kwargs):
        self.db_path = db_path
        self.kwargs = kwargs
        self.closed = False

    def close(self):
        self.closed = True


class TestServiceContainer:
    """Тесты для ServiceContainer"""

    def test_container_creates_config_lazily(self, monkeypatch):
        """Проверить что Config создается lazy (при первом обращении)"""
        fake_config = FakeConfig()
        load_config_called = []

        def mock_load_config():
            load_config_called.append(True)
            return fake_config

        monkeypatch.setattr("utils.config.load_config", mock_load_config)

        container = ServiceContainer()

        # Config не загружен сразу
        assert len(load_config_called) == 0

        # Config загружается при первом обращении
        config = container.config
        assert config is fake_config
        assert len(load_config_called) == 1

        # Повторное обращение возвращает тот же instance (singleton)
        config2 = container.config
        assert config2 is config
        assert len(load_config_called) == 1  # load_config вызван только раз

    def test_container_accepts_config_in_init(self):
        """Проверить что можно передать Config в конструктор"""
        fake_config = FakeConfig()
        container = ServiceContainer(config=fake_config)

        config = container.config
        assert config is fake_config

    def test_container_creates_database_instances(self, monkeypatch):
        """Проверить что create_database создает новые instances"""
        fake_config = FakeConfig()
        container = ServiceContainer(config=fake_config)

        # Mock Database
        created_databases = []

        def mock_database_init(db_path, **kwargs):
            db = FakeDatabase(db_path, **kwargs)
            created_databases.append(db)
            return db

        monkeypatch.setattr("database.db.Database", mock_database_init)

        # Создаем первый instance
        db1 = container.create_database()
        assert db1.db_path == ":memory:"
        assert db1.kwargs == {"timeout": 30}
        assert len(created_databases) == 1

        # Создаем второй instance - должен быть НОВЫЙ
        db2 = container.create_database()
        assert db2 is not db1  # Разные instances!
        assert len(created_databases) == 2

    def test_container_set_database_factory(self):
        """Проверить что можно установить кастомную фабрику Database"""
        container = ServiceContainer()

        # Создаем mock фабрику
        mock_db = FakeDatabase(":memory:", custom=True)

        def custom_factory():
            return mock_db

        container.set_database_factory(custom_factory)

        # Теперь create_database использует кастомную фабрику
        db = container.create_database()
        assert db is mock_db
        assert db.kwargs == {"custom": True}

    def test_container_set_config(self):
        """Проверить set_config для подмены конфигурации"""
        container = ServiceContainer()

        fake_config1 = FakeConfig()
        fake_config2 = FakeConfig()
        fake_config2.log_level = "DEBUG"

        container.set_config(fake_config1)
        assert container.config is fake_config1

        container.set_config(fake_config2)
        assert container.config is fake_config2
        assert container.config.log_level == "DEBUG"

    def test_global_container_singleton(self):
        """Проверить что get_container возвращает singleton"""
        reset_container()  # Сбрасываем global state

        container1 = get_container()
        container2 = get_container()

        assert container1 is container2  # Тот же instance

    def test_set_global_container(self):
        """Проверить set_container для подмены global container"""
        reset_container()

        custom_container = ServiceContainer(config=FakeConfig())
        set_container(custom_container)

        container = get_container()
        assert container is custom_container

    def test_reset_container(self):
        """Проверить reset_container"""
        container1 = get_container()
        assert container1 is not None

        reset_container()

        container2 = get_container()
        assert container2 is not container1  # Новый instance после reset


class TestContainerIntegration:
    """Интеграционные тесты с реальными классами"""

    def test_container_creates_real_database(self):
        """Проверить создание реального Database через container"""
        from database.db import Database

        # Используем FakeConfig для простоты
        fake_config = FakeConfig()
        container = ServiceContainer(config=fake_config)

        db = container.create_database()

        try:
            assert isinstance(db, Database)
            assert db.db_path == ":memory:"

            # Проверяем что БД работает
            cursor = db.conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            db.close()
