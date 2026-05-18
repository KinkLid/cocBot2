from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import PlayerAccount, ReturnEvent, TelegramPlayerLink, TelegramUser
from app.services.clan_sync import ClanSyncService
from app.services.auth import AuthService
from app.services.notifications import AdminNotifier
from app.services.registration import RegistrationService, UserAlreadyRegisteredError
from app.utils.time import utcnow
from tests.fakes import FakeSender
from tests.helpers import make_clan_member
from tests.helpers import make_player_profile


@pytest.mark.asyncio
async def test_successful_registration_via_player_token(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")

    result = await RegistrationService(session, fake_clash_client).register_player(
        telegram_id=100,
        username="tester",
        player_tag="#P2",
        player_token="GOOD",
    )

    assert result.player_tag == "#P2"
    assert result.already_linked is False
    user = await session.scalar(select(TelegramUser).where(TelegramUser.telegram_id == 100))
    assert user is not None
    count = await session.scalar(select(func.count(TelegramPlayerLink.id)))
    assert count == 1


@pytest.mark.asyncio
async def test_registration_fails_with_invalid_player_token(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "BAD")] = False
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")

    with pytest.raises(ValueError, match="Неверный player token"):
        await RegistrationService(session, fake_clash_client).register_player(
            telegram_id=100,
            username="tester",
            player_tag="#P2",
            player_token="BAD",
        )


@pytest.mark.asyncio
async def test_single_telegram_user_can_link_multiple_accounts(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD1")] = True
    fake_clash_client.verify_map[("#P8", "GOOD2")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")
    fake_clash_client.players["#P8"] = make_player_profile("#P8", "Bravo")
    service = RegistrationService(session, fake_clash_client)

    await service.register_player(telegram_id=100, username="tester", player_tag="#P2", player_token="GOOD1")
    await service.add_player_account(telegram_id=100, username="tester", player_tag="#P8", player_token="GOOD2")

    links = list((await session.execute(select(TelegramPlayerLink).order_by(TelegramPlayerLink.player_tag))).scalars())
    assert [link.player_tag for link in links] == ["#P2", "#P8"]


@pytest.mark.asyncio
async def test_registration_does_not_create_duplicate_links(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")
    service = RegistrationService(session, fake_clash_client)

    first = await service.register_player(telegram_id=100, username="tester", player_tag="#P2", player_token="GOOD")
    second = await service.add_player_account(telegram_id=100, username="tester", player_tag="#P2", player_token="GOOD")

    assert first.already_linked is False
    assert second.already_linked is True
    count = await session.scalar(select(func.count(TelegramPlayerLink.id)))
    assert count == 1


@pytest.mark.asyncio
async def test_repeat_primary_registration_is_blocked(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD1")] = True
    fake_clash_client.verify_map[("#P8", "GOOD2")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")
    fake_clash_client.players["#P8"] = make_player_profile("#P8", "Bravo")
    service = RegistrationService(session, fake_clash_client)

    await service.register_player(telegram_id=100, username="tester", player_tag="#P2", player_token="GOOD1")
    with pytest.raises(UserAlreadyRegisteredError, match="Повторная регистрация не требуется"):
        await service.register_player(telegram_id=100, username="tester", player_tag="#P8", player_token="GOOD2")

    users_count = await session.scalar(select(func.count(TelegramUser.id)))
    links_count = await session.scalar(select(func.count(TelegramPlayerLink.id)))
    assert users_count == 1
    assert links_count == 1


def test_admin_rights_checked_by_telegram_id(app_yaml_config):
    auth = AuthService(app_yaml_config)
    assert auth.is_admin(1) is True
    assert auth.is_admin(999) is False


@pytest.mark.asyncio
async def test_registration_preserves_existing_membership_fields(session, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha Renamed", town_hall=16)
    service = RegistrationService(session, fake_clash_client)

    await service.players.upsert_player(
        player_tag="#P2",
        name="Alpha",
        town_hall=15,
        now=utcnow(),
        clan_tag="#CLAN",
        clan_name="Main Clan",
        clan_rank=7,
        in_clan=True,
    )
    await session.commit()

    await service.register_player(telegram_id=100, username="tester", player_tag="#P2", player_token="GOOD")

    player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P2"))
    assert player is not None
    assert player.current_in_clan is True
    assert player.current_clan_tag == "#CLAN"
    assert player.current_clan_name == "Main Clan"
    assert player.current_clan_rank == 7


@pytest.mark.asyncio
async def test_registration_does_not_trigger_false_return_on_next_sync(session, fake_clash_client, app_yaml_config):
    fake_clash_client.verify_map[("#P2", "GOOD")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha", town_hall=15)
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1, town_hall=15)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    sync = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)

    await sync.sync_members()
    await RegistrationService(session, fake_clash_client).register_player(
        telegram_id=100,
        username="tester",
        player_tag="#P2",
        player_token="GOOD",
    )
    await sync.sync_members()

    events = list((await session.execute(select(ReturnEvent).where(ReturnEvent.player_tag == "#P2"))).scalars())
    assert events == []
    assert sender.sent == []
