from dataclasses import dataclass, field


@dataclass
class Marketplace:
    """Настройки конкретного маркетплейса для процессора."""

    name: str
    target_channel: str
    top_n: int = 10
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    display_name: str | None = None
    keywords_lower: list[str] = field(init=False, default_factory=list)
    exclude_keywords_lower: list[str] = field(init=False, default_factory=list)
    combined_exclude_keywords_lower: list[str] = field(init=False, default_factory=list)

    def __post_init__(self):
        self.keywords_lower = [keyword.lower() for keyword in self.keywords]
        self.exclude_keywords_lower = [keyword.lower() for keyword in self.exclude_keywords]
