from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import NsfwModerationConfig
from app.services.chat_moderation_mutes import ChatModerationMuteService
from app.services.nsfw_settings import NsfwRuntimeSettings, NsfwSettingsService, as_runtime

logger = logging.getLogger(__name__)

_NSFW_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
}


@dataclass(frozen=True, slots=True)
class NsfwQueueItem:
    chat_id: int
    message_id: int
    telegram_user_id: int
    username: str | None
    display_name: str | None
    file_id: str
    media_kind: str


@dataclass(frozen=True, slots=True)
class NsfwStatus:
    enabled: bool
    scan_interval_seconds: int
    queued: int
    queue_max_size: int
    worker_running: bool
    last_result: str | None


class NsfwModerationService:
    def __init__(
        self,
        bot: Bot,
        session_maker: async_sessionmaker[AsyncSession],
        config: NsfwModerationConfig,
    ) -> None:
        self.bot = bot
        self.session_maker = session_maker
        self.config = config
        self._chat_ids = set(config.chat_ids)
        self._queue: asyncio.Queue[NsfwQueueItem] = asyncio.Queue(maxsize=config.queue_max_size)
        self._runtime = NsfwRuntimeSettings(
            enabled=config.enabled,
            scan_interval_seconds=config.scan_interval_seconds,
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._detector: Any | None = None
        self._last_result: str | None = None

    async def initialize(self) -> None:
        async with self.session_maker() as session:
            row = await NsfwSettingsService(session).get_or_create(
                default_enabled=self.config.enabled,
                default_scan_interval_seconds=self.config.scan_interval_seconds,
            )
            self._runtime = as_runtime(row)
            await session.commit()

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run_worker(), name="nsfw-moderation-worker")

    async def close(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)

    def is_target_chat(self, chat_id: int) -> bool:
        return chat_id in self._chat_ids

    @property
    def enabled(self) -> bool:
        return self._runtime.enabled

    def enqueue(self, item: NsfwQueueItem) -> bool:
        if not self._runtime.enabled or item.chat_id not in self._chat_ids:
            return False
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            logger.error(
                "NSFW moderation queue full: chat_id=%s message_id=%s max_size=%s",
                item.chat_id,
                item.message_id,
                self.config.queue_max_size,
            )
            return False

    async def update_runtime(
        self,
        *,
        enabled: bool | None = None,
        scan_interval_seconds: int | None = None,
    ) -> NsfwRuntimeSettings:
        async with self.session_maker() as session:
            row = await NsfwSettingsService(session).update(
                enabled=enabled,
                scan_interval_seconds=scan_interval_seconds,
                default_enabled=self.config.enabled,
                default_scan_interval_seconds=self.config.scan_interval_seconds,
            )
            await session.commit()
            self._runtime = as_runtime(row)
        return self._runtime

    def status(self) -> NsfwStatus:
        return NsfwStatus(
            enabled=self._runtime.enabled,
            scan_interval_seconds=self._runtime.scan_interval_seconds,
            queued=self._queue.qsize(),
            queue_max_size=self.config.queue_max_size,
            worker_running=self._worker_task is not None and not self._worker_task.done(),
            last_result=self._last_result,
        )

    async def _run_worker(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if self._runtime.enabled:
                    await self._process(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "NSFW moderation failed: chat_id=%s message_id=%s kind=%s",
                    item.chat_id,
                    item.message_id,
                    item.media_kind,
                )
                self._last_result = f"ошибка: {item.media_kind}"
            finally:
                self._queue.task_done()
            await asyncio.sleep(self._runtime.scan_interval_seconds)

    async def _process(self, item: NsfwQueueItem) -> None:
        if item.media_kind == "image":
            unsafe, label, score = await self._scan_image_file_id(item.file_id)
        elif item.media_kind == "video":
            unsafe, label, score = await self._scan_video_file_id(item.file_id)
        else:
            self._last_result = f"пропущен неподдерживаемый тип: {item.media_kind}"
            return

        self._last_result = (
            f"NSFW {label} {score:.2f}" if unsafe and label is not None else f"safe: {item.media_kind}"
        )
        if not unsafe:
            return

        await self._apply_action(item, rule_id=f"nsfw:{label or 'unknown'}:{score:.2f}")

    async def _scan_image_file_id(self, file_id: str) -> tuple[bool, str | None, float]:
        buffer = BytesIO()
        await self.bot.download(file_id, destination=buffer)
        return await asyncio.to_thread(self._detect_image, buffer.getvalue())

    async def _scan_video_file_id(self, file_id: str) -> tuple[bool, str | None, float]:
        with tempfile.TemporaryDirectory(prefix="cocbot-nsfw-") as directory:
            path = Path(directory) / "media.bin"
            await self.bot.download(file_id, destination=path)
            return await asyncio.to_thread(self._detect_video, path)

    def _load_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        from nudenet import NudeDetector

        try:
            import cv2

            cv2.setNumThreads(1)
        except Exception:
            logger.exception("Unable to limit OpenCV threads")
        self._detector = NudeDetector(providers=["CPUExecutionProvider"], inference_resolution=320)
        return self._detector

    def _detect_image(self, image: Any) -> tuple[bool, str | None, float]:
        detector = self._load_detector()
        detections = detector.detect(image)
        best_label: str | None = None
        best_score = 0.0
        for detection in detections:
            label = str(detection.get("class", ""))
            score = float(detection.get("score", 0.0))
            if label in _NSFW_CLASSES and score >= self.config.score_threshold and score > best_score:
                best_label = label
                best_score = score
        return best_label is not None, best_label, best_score

    def _detect_video(self, path: Path) -> tuple[bool, str | None, float]:
        import cv2

        capture = cv2.VideoCapture(str(path))
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if frame_count <= 0:
                logger.warning("NSFW video decoder returned no frames: %s", path)
                return False, None, 0.0
            sample_count = min(self.config.max_video_frames, frame_count)
            if sample_count == 1:
                indexes = [frame_count // 2]
            else:
                indexes = [round(index * (frame_count - 1) / (sample_count - 1)) for index in range(sample_count)]
            best_label: str | None = None
            best_score = 0.0
            for frame_index in indexes:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    continue
                unsafe, label, score = self._detect_image(frame)
                if score > best_score:
                    best_label = label
                    best_score = score
                if unsafe:
                    return True, label, score
            return False, best_label, best_score
        finally:
            capture.release()

    async def _apply_action(self, item: NsfwQueueItem, *, rule_id: str) -> None:
        deleted = False
        muted = False
        author_is_admin = False
        try:
            await self.bot.delete_message(chat_id=item.chat_id, message_id=item.message_id)
            deleted = True
        except TelegramAPIError as exc:
            logger.warning(
                "Unable to delete NSFW message: chat_id=%s message_id=%s user_id=%s error=%s",
                item.chat_id,
                item.message_id,
                item.telegram_user_id,
                type(exc).__name__,
            )

        try:
            member = await self.bot.get_chat_member(chat_id=item.chat_id, user_id=item.telegram_user_id)
            author_is_admin = member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
            chat = await self.bot.get_chat(item.chat_id)
            if not author_is_admin and chat.type == ChatType.SUPERGROUP:
                muted_at = datetime.now(UTC)
                muted_until = muted_at + timedelta(minutes=self.config.mute_minutes)
                await self.bot.restrict_chat_member(
                    chat_id=item.chat_id,
                    user_id=item.telegram_user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=muted_until,
                )
                muted = True
                try:
                    async with self.session_maker() as session:
                        await ChatModerationMuteService(session).record_mute(
                            chat_id=item.chat_id,
                            telegram_user_id=item.telegram_user_id,
                            username=item.username,
                            display_name=item.display_name,
                            rule_id=rule_id[:100],
                            muted_at=muted_at,
                            muted_until=muted_until,
                        )
                        await session.commit()
                except Exception:
                    logger.exception(
                        "Unable to persist NSFW mute: chat_id=%s user_id=%s",
                        item.chat_id,
                        item.telegram_user_id,
                    )
        except TelegramAPIError as exc:
            logger.warning(
                "Unable to restrict NSFW sender: chat_id=%s user_id=%s error=%s",
                item.chat_id,
                item.telegram_user_id,
                type(exc).__name__,
            )

        logger.warning(
            "NSFW moderation action: chat_id=%s message_id=%s user_id=%s rule=%s deleted=%s muted=%s admin=%s",
            item.chat_id,
            item.message_id,
            item.telegram_user_id,
            rule_id,
            deleted,
            muted,
            author_is_admin,
        )
