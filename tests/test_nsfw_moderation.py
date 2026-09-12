from __future__ import annotations

from aiogram.types import Chat, Document, Message, PhotoSize, User

from app.bot.middlewares.nsfw_moderation import _extract_media
from app.config.settings import NsfwModerationConfig
from app.services.nsfw_moderation import NsfwModerationService, NsfwQueueItem


def _message(**kwargs) -> Message:
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=-1001, type="supergroup", title="test"),
        from_user=User(id=10, is_bot=False, first_name="User"),
        **kwargs,
    )


def test_nsfw_config_is_safe_and_low_resource_by_default() -> None:
    config = NsfwModerationConfig()

    assert config.enabled is False
    assert config.scan_interval_seconds == 30
    assert config.queue_max_size == 50
    assert config.max_video_frames == 8
    assert config.score_threshold == 0.72


def test_extracts_largest_photo() -> None:
    message = _message(
        photo=[
            PhotoSize(file_id="small", file_unique_id="s", width=100, height=100, file_size=100),
            PhotoSize(file_id="large", file_unique_id="l", width=800, height=800, file_size=1000),
        ]
    )

    assert _extract_media(message) == ("large", "image")


def test_extracts_image_document() -> None:
    message = _message(
        document=Document(
            file_id="doc",
            file_unique_id="du",
            file_name="photo.png",
            mime_type="image/png",
        )
    )

    assert _extract_media(message) == ("doc", "image")


def test_detector_flags_only_configured_exposed_classes_above_threshold() -> None:
    class FakeDetector:
        def detect(self, _image):
            return [
                {"class": "BELLY_EXPOSED", "score": 0.99},
                {"class": "FEMALE_BREAST_EXPOSED", "score": 0.80},
            ]

    service = NsfwModerationService(None, None, NsfwModerationConfig(score_threshold=0.72))  # type: ignore[arg-type]
    service._detector = FakeDetector()

    unsafe, label, score = service._detect_image(b"image")

    assert unsafe is True
    assert label == "FEMALE_BREAST_EXPOSED"
    assert score == 0.80


def test_detector_ignores_low_confidence_exposed_class() -> None:
    class FakeDetector:
        def detect(self, _image):
            return [{"class": "MALE_GENITALIA_EXPOSED", "score": 0.50}]

    service = NsfwModerationService(None, None, NsfwModerationConfig(score_threshold=0.72))  # type: ignore[arg-type]
    service._detector = FakeDetector()

    assert service._detect_image(b"image") == (False, None, 0.0)


def test_queue_is_bounded() -> None:
    service = NsfwModerationService(None, None, NsfwModerationConfig(enabled=True, chat_ids=[-1001], queue_max_size=1))  # type: ignore[arg-type]
    item = NsfwQueueItem(
        chat_id=-1001,
        message_id=1,
        telegram_user_id=10,
        username=None,
        display_name="User",
        file_id="file",
        media_kind="image",
    )

    assert service.enqueue(item) is True
    assert service.enqueue(item) is False
