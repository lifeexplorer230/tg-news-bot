import asyncio
from types import SimpleNamespace

from models.category import Category
from services.news_processor import NewsProcessor


class FakeDB:
    def __init__(self, messages):
        self.messages = list(messages)
        self.states = {
            msg["id"]: {
                "processed": 0,
                "rejection_reason": None,
                "gemini_score": None,
                "is_duplicate": False,
            }
            for msg in messages
        }

    def get_unprocessed_messages(self, hours=24):
        return list(self.messages)

    def mark_as_processed(
        self,
        message_id,
        is_duplicate=False,
        gemini_score=None,
        rejection_reason=None,
    ):
        state = self.states.setdefault(
            message_id,
            {
                "processed": 0,
                "rejection_reason": None,
                "gemini_score": None,
                "is_duplicate": False,
            },
        )
        state["processed"] = 1
        state["is_duplicate"] = is_duplicate
        state["gemini_score"] = gemini_score
        state["rejection_reason"] = rejection_reason


class FakeClient:
    async def send_message(self, *args, **kwargs):
        return None


def make_processor(messages, moderation_enabled=False):
    processor = NewsProcessor.__new__(NewsProcessor)
    processor.config = SimpleNamespace(my_personal_account="tester")
    processor.db = FakeDB(messages)
    processor.global_exclude_keywords = ["spam"]
    processor.categories = {
        "ozon": Category(
            name="ozon",
            target_channel="@ozon",
            keywords=[],
            exclude_keywords=["spam"],
            top_n=5,
        ),
        "wildberries": Category(
            name="wildberries",
            target_channel="@wb",
            keywords=[],
            exclude_keywords=["spam"],
            top_n=5,
        ),
    }
    for marketplace in processor.categories.values():
        marketplace.combined_exclude_keywords_lower = ["spam"]
    processor.all_digest_enabled = True
    processor.all_digest_channel = "@all_digest"
    processor.duplicate_threshold = 0.85
    processor.moderation_enabled = moderation_enabled
    processor.all_digest_counts = {
        "wildberries": 1,
        "ozon": 1,
        "general": 1,
    }
    processor.processor_exclude_count = 5
    processor.processor_top_n = 10
    processor.publication_header_template = "TEST HEADER {date}"
    processor.publication_footer_template = ""
    processor.publication_preview_channel = ""
    processor.publication_notify_account = ""
    processor.all_exclude_keywords_lower = {"spam"}

    async def fake_filter_duplicates(msgs):
        return list(msgs), {}

    async def fake_publish_digest(*args, **kwargs):
        return None

    processor.filter_duplicates = fake_filter_duplicates
    processor.publish_digest = fake_publish_digest
    return processor


def test_process_all_categories_marks_all_outcomes():
    messages = [
        {
            "id": 1,
            "text": "Новость про Wildberries",
            "channel_username": "wb_news",
            "message_id": 101,
            "channel_id": 1001,
        },
        {
            "id": 2,
            "text": "Нейтральная новость без выбора",
            "channel_username": "market_news",
            "message_id": 102,
            "channel_id": 1002,
        },
        {
            "id": 3,
            "text": "Это spam реклама курса",
            "channel_username": "spam_channel",
            "message_id": 103,
            "channel_id": 1003,
        },
    ]

    processor = make_processor(messages, moderation_enabled=False)

    def fake_select_three_categories(_messages, wb_count, ozon_count, general_count):
        return {
            "wildberries": [
                {
                    "source_message_id": 1,
                    "source_channel_id": 1001,
                    "title": "Важная новость WB",
                    "description": "Описание новости",
                    "score": 9,
                    "category": "wildberries",
                }
            ],
            "ozon": [],
            "general": [],
        }

    def fake_select_by_categories(_messages, category_counts, chunk_size=50):
        # Wrapper для backwards compatibility с select_three_categories
        return fake_select_three_categories(
            _messages,
            wb_count=category_counts.get("wildberries", 5),
            ozon_count=category_counts.get("ozon", 5),
            general_count=category_counts.get("general", 5),
        )

    processor._gemini_client = SimpleNamespace(
        select_three_categories=fake_select_three_categories,
        select_by_categories=fake_select_by_categories,
    )

    asyncio.run(processor.process_all_categories(FakeClient()))

    states = processor.db.states
    assert states[1]["processed"] == 1
    assert states[1]["gemini_score"] == 9
    assert states[1]["rejection_reason"] is None

    assert states[2]["processed"] == 1
    assert states[2]["rejection_reason"] == "rejected_by_llm"

    assert states[3]["processed"] == 1
    assert states[3]["rejection_reason"] == "rejected_by_exclude_keywords"


def test_process_all_categories_marks_moderator_rejections():
    messages = [
        {
            "id": 10,
            "text": "Новость про Ozon",
            "channel_username": "ozon_news",
            "message_id": 201,
            "channel_id": 2001,
        }
    ]

    processor = make_processor(messages, moderation_enabled=True)

    def fake_select_three_categories(_messages, wb_count, ozon_count, general_count):
        return {
            "wildberries": [],
            "ozon": [
                {
                    "source_message_id": 10,
                    "source_channel_id": 2001,
                    "title": "Новость Ozon",
                    "description": "Описание",
                    "score": 8,
                    "category": "ozon",
                }
            ],
            "general": [],
        }

    def fake_select_by_categories(_messages, category_counts, chunk_size=50):
        # Wrapper для backwards compatibility с select_three_categories
        return fake_select_three_categories(
            _messages,
            wb_count=category_counts.get("wildberries", 5),
            ozon_count=category_counts.get("ozon", 5),
            general_count=category_counts.get("general", 5),
        )

    processor._gemini_client = SimpleNamespace(
        select_three_categories=fake_select_three_categories,
        select_by_categories=fake_select_by_categories,
    )

    async def fake_moderate_categories(client, categories):
        return []

    processor.moderate_categories = fake_moderate_categories

    asyncio.run(processor.process_all_categories(FakeClient()))

    state = processor.db.states[10]
    assert state["processed"] == 1
    assert state["rejection_reason"] == "rejected_by_moderator"
    assert state["gemini_score"] is None
