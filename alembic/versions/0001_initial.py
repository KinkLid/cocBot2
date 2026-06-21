"""initial schema

Revision ID: 0001_initial
Revises: None
Create Date: 2026-04-01 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("town_hall", sa.Integer(), nullable=False),
        sa.Column("current_clan_tag", sa.String(length=20), nullable=True),
        sa.Column("current_clan_name", sa.String(length=100), nullable=True),
        sa.Column("current_clan_rank", sa.Integer(), nullable=True),
        sa.Column("current_in_clan", sa.Boolean(), nullable=False),
        sa.Column("last_seen_in_clan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_absent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_tag"),
    )
    for name, cols in {
        "ix_player_accounts_player_tag": ["player_tag"],
        "ix_player_accounts_current_clan_tag": ["current_clan_tag"],
        "ix_player_accounts_current_in_clan": ["current_in_clan"],
        "ix_player_accounts_last_seen_in_clan_at": ["last_seen_in_clan_at"],
        "ix_player_accounts_first_absent_at": ["first_absent_at"],
    }.items():
        op.create_index(name, "player_accounts", cols)

    op.create_table("telegram_users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("telegram_id", sa.BigInteger(), nullable=False), sa.Column("username", sa.String(length=255), nullable=True), sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True), sa.UniqueConstraint("telegram_id"))
    op.create_index("ix_telegram_users_telegram_id", "telegram_users", ["telegram_id"])

    op.create_table("telegram_player_links", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("telegram_user_id", sa.Integer(), nullable=False), sa.Column("player_tag", sa.String(length=20), nullable=False), sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["telegram_user_id"], ["telegram_users.id"], ondelete="CASCADE"), sa.UniqueConstraint("telegram_user_id", "player_tag", name="uq_telegram_player_link"))
    op.create_index("ix_telegram_player_links_telegram_user_id", "telegram_player_links", ["telegram_user_id"])
    op.create_index("ix_telegram_player_links_player_tag", "telegram_player_links", ["player_tag"])

    op.create_table("clan_membership_history", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("player_id", sa.Integer(), nullable=False), sa.Column("clan_tag", sa.String(length=20), nullable=False), sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False), sa.Column("left_at", sa.DateTime(timezone=True), nullable=True), sa.ForeignKeyConstraint(["player_id"], ["player_accounts.id"], ondelete="CASCADE"))
    op.create_index("ix_clan_membership_history_player_id", "clan_membership_history", ["player_id"])
    op.create_index("ix_clan_membership_history_clan_tag", "clan_membership_history", ["clan_tag"])

    op.create_table("clan_settings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("clan_tag", sa.String(length=20), nullable=False), sa.Column("clan_chat_url", sa.String(length=500), nullable=True), sa.Column("log_level", sa.String(length=20), nullable=False), sa.UniqueConstraint("clan_tag"))
    op.create_index("ix_clan_settings_clan_tag", "clan_settings", ["clan_tag"])

    op.create_table("cycle_boundaries", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_key", sa.String(length=100), nullable=False), sa.Column("boundary_at", sa.DateTime(timezone=True), nullable=False), sa.Column("description", sa.String(length=255), nullable=False), sa.UniqueConstraint("source_key", name="uq_cycle_boundary_source_key"))
    op.create_index("ix_cycle_boundaries_source_key", "cycle_boundaries", ["source_key"])
    op.create_index("ix_cycle_boundaries_boundary_at", "cycle_boundaries", ["boundary_at"])

    op.create_table("departed_players_archive", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("player_tag", sa.String(length=20), nullable=False), sa.Column("last_known_name", sa.String(length=100), nullable=False), sa.Column("previous_clan_tag", sa.String(length=20), nullable=False), sa.Column("departed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("purged_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("player_tag"))
    op.create_index("ix_departed_players_archive_player_tag", "departed_players_archive", ["player_tag"])
    op.create_index("ix_departed_players_archive_departed_at", "departed_players_archive", ["departed_at"])
    op.create_index("ix_departed_players_archive_purged_at", "departed_players_archive", ["purged_at"])

    op.create_table("return_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("player_tag", sa.String(length=20), nullable=False), sa.Column("player_name", sa.String(length=100), nullable=False), sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False), sa.Column("was_purged", sa.Boolean(), nullable=False))
    op.create_index("ix_return_events_player_tag", "return_events", ["player_tag"])
    op.create_index("ix_return_events_returned_at", "return_events", ["returned_at"])

    op.create_table("admin_notification_history", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False), sa.Column("event_key", sa.String(length=255), nullable=False), sa.Column("event_type", sa.String(length=50), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("admin_telegram_id", "event_key", name="uq_admin_event"))
    op.create_index("ix_admin_notification_history_admin_telegram_id", "admin_notification_history", ["admin_telegram_id"])
    op.create_index("ix_admin_notification_history_event_key", "admin_notification_history", ["event_key"])
    op.create_index("ix_admin_notification_history_event_type", "admin_notification_history", ["event_type"])

    op.create_table("wars", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("war_uid", sa.String(length=255), nullable=False), sa.Column("clan_tag", sa.String(length=20), nullable=False), sa.Column("clan_name", sa.String(length=100), nullable=False), sa.Column("opponent_tag", sa.String(length=20), nullable=False), sa.Column("opponent_name", sa.String(length=100), nullable=False), sa.Column("war_type", sa.String(length=7), nullable=False), sa.Column("state", sa.String(length=11), nullable=False), sa.Column("league_group_id", sa.String(length=100), nullable=True), sa.Column("cwl_season", sa.String(length=20), nullable=True), sa.Column("round_index", sa.Integer(), nullable=True), sa.Column("team_size", sa.Integer(), nullable=False), sa.Column("is_friendly", sa.Boolean(), nullable=False), sa.Column("start_time", sa.DateTime(timezone=True), nullable=True), sa.Column("end_time", sa.DateTime(timezone=True), nullable=True), sa.Column("preparation_start_time", sa.DateTime(timezone=True), nullable=True), sa.Column("source_payload", sa.JSON(), nullable=False), sa.UniqueConstraint("war_uid", name="uq_war_uid"))
    for name, cols in {"ix_wars_war_uid": ["war_uid"], "ix_wars_clan_tag": ["clan_tag"], "ix_wars_state": ["state"], "ix_wars_league_group_id": ["league_group_id"], "ix_wars_cwl_season": ["cwl_season"], "ix_wars_start_time": ["start_time"], "ix_wars_end_time": ["end_time"]}.items(): op.create_index(name, "wars", cols)

    op.create_table("war_participants", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("war_id", sa.Integer(), nullable=False), sa.Column("player_id", sa.Integer(), nullable=True), sa.Column("player_tag", sa.String(length=20), nullable=False), sa.Column("name", sa.String(length=100), nullable=False), sa.Column("map_position", sa.Integer(), nullable=False), sa.Column("town_hall", sa.Integer(), nullable=False), sa.Column("is_own_clan", sa.Boolean(), nullable=False), sa.ForeignKeyConstraint(["player_id"], ["player_accounts.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["war_id"], ["wars.id"], ondelete="CASCADE"), sa.UniqueConstraint("war_id", "player_tag", name="uq_war_participant"))
    for name, cols in {"ix_war_participants_war_id": ["war_id"], "ix_war_participants_player_id": ["player_id"], "ix_war_participants_player_tag": ["player_tag"]}.items(): op.create_index(name, "war_participants", cols)

    op.create_table("attacks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("war_id", sa.Integer(), nullable=False), sa.Column("attacker_player_id", sa.Integer(), nullable=True), sa.Column("attacker_tag", sa.String(length=20), nullable=False), sa.Column("attacker_name", sa.String(length=100), nullable=False), sa.Column("attacker_position", sa.Integer(), nullable=False), sa.Column("attacker_town_hall", sa.Integer(), nullable=False), sa.Column("defender_tag", sa.String(length=20), nullable=False), sa.Column("defender_name", sa.String(length=100), nullable=False), sa.Column("defender_position", sa.Integer(), nullable=False), sa.Column("defender_town_hall", sa.Integer(), nullable=False), sa.Column("stars", sa.Integer(), nullable=False), sa.Column("destruction", sa.Float(), nullable=False), sa.Column("attack_order", sa.Integer(), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["attacker_player_id"], ["player_accounts.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["war_id"], ["wars.id"], ondelete="CASCADE"), sa.UniqueConstraint("war_id", "attacker_tag", "defender_tag", "attack_order", name="uq_attack_identity"))
    for name, cols in {"ix_attacks_war_id": ["war_id"], "ix_attacks_attacker_player_id": ["attacker_player_id"], "ix_attacks_attacker_tag": ["attacker_tag"], "ix_attacks_observed_at": ["observed_at"]}.items(): op.create_index(name, "attacks", cols)

    op.create_table("violations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("attack_id", sa.Integer(), nullable=False), sa.Column("war_id", sa.Integer(), nullable=False), sa.Column("player_tag", sa.String(length=20), nullable=False), sa.Column("code", sa.String(length=10), nullable=False), sa.Column("reason_text", sa.String(length=255), nullable=False), sa.Column("player_position", sa.Integer(), nullable=False), sa.Column("target_position", sa.Integer(), nullable=False), sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["attack_id"], ["attacks.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["war_id"], ["wars.id"], ondelete="CASCADE"), sa.UniqueConstraint("attack_id", name="uq_violation_attack"))
    for name, cols in {"ix_violations_attack_id": ["attack_id"], "ix_violations_war_id": ["war_id"], "ix_violations_player_tag": ["player_tag"], "ix_violations_detected_at": ["detected_at"]}.items(): op.create_index(name, "violations", cols)


def downgrade() -> None:
    for table in ["violations", "attacks", "war_participants", "wars", "admin_notification_history", "return_events", "departed_players_archive", "cycle_boundaries", "clan_settings", "clan_membership_history", "telegram_player_links", "telegram_users", "player_accounts"]:
        op.drop_table(table)
