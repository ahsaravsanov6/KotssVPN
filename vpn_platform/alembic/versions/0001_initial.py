"""initial schema: users, devices, device_server_access

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-06

ИЗМЕНЕНО: таблицы servers здесь больше нет — сервера с этого момента
живут в файле (см. app/servers_config.py), полноценная таблица с
миграциями на каждое изменение схемы избыточна при ожидаемых единицах
серверов. device_server_access.server_id — обычная строка (слаг из
servers.yaml), не внешний ключ.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("sub_token", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subscription_expires_at", sa.DateTime(), nullable=True),
        sa.Column("tariff", sa.String(length=32), nullable=False, server_default="standard"),
        sa.Column("trial_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extra_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("referrer_id", sa.Integer(), sa.ForeignKey("users.telegram_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_sub_token", "users", ["sub_token"], unique=True)

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_name", sa.String(length=128), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_devices_uuid", "devices", ["uuid"], unique=True)

    op.create_table(
        "device_server_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        # server_id — слаг из servers.yaml (напр. "nl-1"), НЕ внешний ключ:
        # сервера больше не таблица БД, см. app/servers_config.py.
        sa.Column("server_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("client_remote_id", sa.String(length=255), nullable=True),
        sa.Column("provisioned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("device_id", "server_id", name="uq_device_server"),
    )


def downgrade() -> None:
    op.drop_table("device_server_access")
    op.drop_index("ix_devices_uuid", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_users_sub_token", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
