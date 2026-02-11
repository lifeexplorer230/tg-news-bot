from datetime import date

from utils.constants import NUMBER_EMOJIS


def format_categories_moderation_message(categories: dict[str, list[dict]]) -> str:
    """Формирует текст для модерации по категориям Wildberries/Ozon/General."""

    lines = ["📋 **МОДЕРАЦИЯ: ВСЕ КАТЕГОРИИ**"]
    lines.append("_Нужно выбрать 10 лучших из 15 новостей_\n")

    idx = 1

    if categories.get("wildberries"):
        lines.append("📦 **WILDBERRIES**\n")
        for post in categories["wildberries"]:
            emoji = NUMBER_EMOJIS.get(idx, f"{idx}.")
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10\n")
            idx += 1

    if categories.get("ozon"):
        lines.append("📦 **OZON**\n")
        for post in categories["ozon"]:
            emoji = NUMBER_EMOJIS.get(idx, f"{idx}.")
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10\n")
            idx += 1

    if categories.get("general"):
        lines.append("🛒 **ОБЩИЕ НОВОСТИ**\n")
        for post in categories["general"]:
            emoji = NUMBER_EMOJIS.get(idx, f"{idx}.")
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10\n")
            idx += 1

    lines.append("=" * 50)
    lines.append("📩 Ответь сообщением с номерами для удаления (через пробел)")
    lines.append("🟢 Чтобы одобрить все новости — отправь `0`\n")
    lines.append("🕒 После ответа модератора бот обновит список автоматически")

    return "\n".join(lines)


def format_moderation_message(posts: list[dict], marketplace: str) -> str:
    """Формирует сообщение для модерации конкретного маркетплейса."""
    lines = [f"📋 **МОДЕРАЦИЯ: {marketplace.upper()}**"]
    lines.append("_(Отсортировано по важности)_\n")

    for post in posts:
        emoji = NUMBER_EMOJIS.get(post["moderation_id"], f"{post['moderation_id']}️⃣")
        lines.append(f"{emoji} **{post['title']}**")
        lines.append(f"_{post['description']}_")
        lines.append(f"⭐ {post.get('score', 0)}/10\n")

    lines.append("=" * 50)
    lines.append("📩 Ответь сообщением с номерами для удаления (через пробел)")
    lines.append("🟢 Чтобы одобрить все новости — отправь `0`\n")
    lines.append("🕒 После ответа модератора бот обновит список автоматически")

    return "\n".join(lines)


def format_digest_message(
    posts: list[dict],
    marketplace: str,
    digest_date: date,
    target_channel: str,
) -> str:
    """Возвращает финальный текст дайджеста для публикации в канал."""
    lines: list[str] = [
        f"📌 Главные новости {marketplace.upper()} за {digest_date.strftime('%d-%m-%Y')}\n"
    ]

    for idx, post in enumerate(posts, 1):
        emoji = NUMBER_EMOJIS.get(idx, f"{idx}️⃣")
        lines.append(f"{emoji} **{post['title']}**\n")
        lines.append(f"{post['description']}\n")

        if post.get("source_link"):
            lines.append(f"{post['source_link']}\n")

    lines.append("_" * 36)
    lines.append(f"Подпишись на новости {marketplace.upper()}")
    lines.append(target_channel)

    return "\n".join(lines)


def ensure_post_fields(post: dict) -> dict:
    """
    QA-1: Fallback-форматирование для постов без title/description.

    Гарантирует наличие обязательных полей в посте.
    Если title или description отсутствуют, извлекаются из text.

    Args:
        post: Словарь с данными поста

    Returns:
        Валидированный пост с гарантированными полями title, description
    """
    if "title" not in post or not post["title"]:
        text = post.get("text", "")
        if text:
            lines = text.split("\n", 1)
            first_line = lines[0].strip()
            words = first_line.split()
            post["title"] = " ".join(words[:7]) if len(words) > 7 else first_line
        else:
            post["title"] = "Без заголовка"

    if "description" not in post or not post["description"]:
        text = post.get("text", "")
        if text:
            lines = text.split("\n", 1)
            if len(lines) > 1:
                post["description"] = lines[1].strip()[:200]
            else:
                words = text.split()
                post["description"] = " ".join(words[7:]) if len(words) > 7 else text
        else:
            post["description"] = "Описание отсутствует"

    MAX_DESCRIPTION_LENGTH = 250
    if len(post.get("description", "")) > MAX_DESCRIPTION_LENGTH:
        post["description"] = post["description"][:MAX_DESCRIPTION_LENGTH].rsplit(" ", 1)[0] + "..."

    return post
