"""Dependency Injection Container для управления зависимостями"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database.db import Database
    from utils.config import Config


class ServiceContainer:
    """
    DI Container для централизованного управления зависимостями

    Принципы:
    - Config - singleton (загружается один раз)
    - Database - factory (каждый компонент создает свой instance)
    - Легко подменяемые зависимости для тестов
    """

    def __init__(self, config: Config | None = None):
        """
        Инициализация контейнера

        Args:
            config: Конфигурация (если None, будет загружена через load_config)
        """
        self._config = config
        self._database_factory = None

    @property
    def config(self) -> Config:
        """
        Получить singleton instance Config

        Returns:
            Config instance
        """
        if self._config is None:
            from utils.config import load_config

            self._config = load_config()
        return self._config

    def create_database(self) -> Database:
        """
        Создать новый instance Database

        Каждый вызов создает НОВЫЙ экземпляр Database с собственным
        connection. Это необходимо для SQLite thread safety.

        Returns:
            Database instance
        """
        if self._database_factory is not None:
            # Используем кастомную фабрику (для тестов)
            return self._database_factory()

        # Стандартная фабрика
        from database.db import Database

        return Database(
            self.config.db_path,
            **self.config.database_settings(),
        )

    def set_database_factory(self, factory):
        """
        Установить кастомную фабрику для Database (для тестов)

        Args:
            factory: Callable который возвращает Database instance
        """
        self._database_factory = factory

    def set_config(self, config: Config):
        """
        Установить Config (для тестов)

        Args:
            config: Config instance
        """
        self._config = config


# Global container instance
_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    """
    Получить global ServiceContainer instance

    Returns:
        ServiceContainer
    """
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container


def set_container(container: ServiceContainer):
    """
    Установить global ServiceContainer (для тестов)

    Args:
        container: ServiceContainer instance
    """
    global _container
    _container = container


def reset_container():
    """Сбросить global container (для тестов)"""
    global _container
    _container = None
