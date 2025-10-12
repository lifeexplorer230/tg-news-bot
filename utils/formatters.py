from datetime import date


def format_categories_moderation_message(categories: dict[str, list[dict]]) -> str:
    """Формирует текст для модерации по категориям Wildberries/Ozon/General."""
    number_emojis = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
        11: "1️⃣1️⃣",
        12: "1️⃣2️⃣",
        13: "1️⃣3️⃣",
        14: "1️⃣4️⃣",
        15: "1️⃣5️⃣",
    }

    lines = ["📋 **МОДЕРАЦИЯ: ВСЕ КАТЕГОРИИ**"]
    lines.append("_Нужно выбрать 10 лучших из 15 новостей_\n")

    idx = 1

    if categories.get("wildberries"):
        lines.append("📦 **WILDBERRIES**\n")
        for post in categories["wildberries"]:
            emoji = number_emojis.get(idx, f"{idx}.")
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10\n")
            idx += 1

    if categories.get("ozon"):
        lines.append("📦 **OZON**\n")
        for post in categories["ozon"]:
            emoji = number_emojis.get(idx, f"{idx}.")
            lines.append(f"{emoji} **{post['title']}**")
            lines.append(f"_{post['description'][:100]}..._")
            lines.append(f"⭐ {post.get('score', 0)}/10\n")
            idx += 1

    if categories.get("general"):
        lines.append("🛒 **ОБЩИЕ НОВОСТИ**\n")
        for post in categories["general"]:
            emoji = number_emojis.get(idx, f"{idx}.")
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
    number_emojis = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }

    lines = [f"📋 **МОДЕРАЦИЯ: {marketplace.upper()}**"]
    lines.append("_(Отсортировано по важности)_\n")

    for post in posts:
        emoji = number_emojis.get(post["moderation_id"], f"{post['moderation_id']}️⃣")
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

    number_emojis = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }

    for idx, post in enumerate(posts, 1):
        emoji = number_emojis.get(idx, f"{idx}️⃣")
        lines.append(f"{emoji} **{post['title']}**\n")
        lines.append(f"{post['description']}\n")

        if post.get("source_link"):
            lines.append(f"{post['source_link']}\n")

    lines.append("_" * 36)
    lines.append(f"Подпишись на новости {marketplace.upper()}")
    lines.append(target_channel)

    return "\n".join(lines)
