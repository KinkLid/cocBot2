from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.chat_moderation_mutes import ChatModerationMuteService


async def test_record_update_list_and_remove_mute(session) -> None:
    service = ChatModerationMuteService(session)
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)

    row = await service.record_mute(
        chat_id=-100123,
        telegram_user_id=777,
        username="user777",
        display_name="Test User",
        rule_id="configured_term_1",
        muted_at=now,
        muted_until=now + timedelta(minutes=60),
    )
    await session.commit()

    active = await service.active_mutes(chat_ids=[-100123], now=now + timedelta(minutes=1))
    assert [item.id for item in active] == [row.id]
    assert active[0].telegram_user_id == 777

    updated = await service.record_mute(
        chat_id=-100123,
        telegram_user_id=777,
        username="renamed",
        display_name="Renamed User",
        rule_id="ru_ethnic_slur",
        muted_at=now + timedelta(minutes=10),
        muted_until=now + timedelta(minutes=120),
    )
    await session.commit()

    assert updated.id == row.id
    assert updated.username == "renamed"
    assert updated.rule_id == "ru_ethnic_slur"

    removed = await service.remove_for_user(chat_id=-100123, telegram_user_id=777)
    await session.commit()
    assert removed is True
    assert await service.active_mutes(chat_ids=[-100123], now=now) == []


async def test_expired_mute_is_not_listed(session) -> None:
    service = ChatModerationMuteService(session)
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
    await service.record_mute(
        chat_id=-100123,
        telegram_user_id=888,
        username=None,
        display_name=None,
        rule_id="configured_term_2",
        muted_at=now - timedelta(hours=2),
        muted_until=now - timedelta(hours=1),
    )
    await session.commit()

    assert await service.active_mutes(chat_ids=[-100123], now=now) == []
