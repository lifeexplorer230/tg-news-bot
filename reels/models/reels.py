"""
Модели данных для Reels сценариев

Содержит структуры данных для сценариев Instagram Reels.
"""

from typing import List

from pydantic import BaseModel, Field


class Script(BaseModel):
    """Структура сценария для Reels (30 секунд)"""

    hook: str = Field(
        ...,
        min_length=10,
        max_length=200,
        description="Hook (0-3 сек): Захватывающее начало"
    )
    main_content: str = Field(
        ...,
        min_length=50,
        max_length=1000,
        description="Main Content (3-25 сек): Основной контент"
    )
    cta: str = Field(
        ...,
        min_length=10,
        max_length=200,
        description="CTA (25-30 сек): Призыв к действию"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "hook": "Вы не поверите, что OpenAI только что анонсировала!",
                "main_content": "GPT-5 превосходит все ожидания: на 40% быстрее, мультимодальность из коробки, и стоимость использования снижена вдвое. Это означает революцию для всех разработчиков AI приложений...",
                "cta": "Сохрани пост, чтобы не пропустить релиз! Подписывайся на канал!"
            }
        }


class ReelsScenario(BaseModel):
    """Полный сценарий для Instagram Reels"""

    news_id: str = Field(
        ...,
        description="ID исходной новости"
    )
    title: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="Заголовок видео"
    )
    duration: int = Field(
        default=30,
        ge=15,
        le=90,
        description="Длительность видео в секундах"
    )

    # Сценарий
    script: Script = Field(
        ...,
        description="Структурированный сценарий (hook, content, CTA)"
    )

    # Дополнительные рекомендации
    visual_suggestions: List[str] = Field(
        ...,
        min_length=3,
        max_length=10,
        description="Предложения по визуалу (что показывать)"
    )
    hashtags: List[str] = Field(
        ...,
        min_length=5,
        max_length=10,
        description="Релевантные хэштеги"
    )
    music_mood: str = Field(
        ...,
        description="Настроение музыки (энергичная, спокойная, драматичная, мотивирующая)"
    )
    target_audience: str = Field(
        ...,
        description="Описание целевой аудитории"
    )

    def get_formatted_hashtags(self) -> str:
        """
        Получить хэштеги в виде строки для публикации

        Returns:
            Строка с хэштегами через пробел
        """
        # Убедиться что все хэштеги начинаются с #
        formatted = []
        for tag in self.hashtags:
            if not tag.startswith('#'):
                formatted.append(f'#{tag}')
            else:
                formatted.append(tag)
        return ' '.join(formatted)

    def get_total_script_length(self) -> int:
        """
        Получить общую длину сценария в символах

        Returns:
            Количество символов
        """
        return len(self.script.hook) + len(self.script.main_content) + len(self.script.cta)

    class Config:
        json_schema_extra = {
            "example": {
                "news_id": "news_001",
                "title": "GPT-5 от OpenAI: Революция в AI!",
                "duration": 30,
                "script": {
                    "hook": "Вы не поверите, что OpenAI только что анонсировала!",
                    "main_content": "GPT-5 превосходит все ожидания...",
                    "cta": "Сохрани пост! Подписывайся!"
                },
                "visual_suggestions": [
                    "Анимация логотипа OpenAI",
                    "Графики сравнения производительности",
                    "Скриншоты интерфейса GPT-5",
                    "Реакция разработчиков в соцсетях"
                ],
                "hashtags": [
                    "#gpt5",
                    "#openai",
                    "#ai",
                    "#artificialintelligence",
                    "#tech"
                ],
                "music_mood": "энергичная",
                "target_audience": "Разработчики, AI энтузиасты, технологические стартапы, 25-40 лет"
            }
        }
