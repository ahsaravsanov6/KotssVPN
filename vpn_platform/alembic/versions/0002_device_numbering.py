"""add per-user device numbering (device_number, next_device_number)

Revision ID: 0002_device_numbering
Revises: 0001_initial
Create Date: 2026-07-24

Добавляет:
  - users.next_device_number  — счётчик следующего номера устройства
    этого пользователя (см. app/db/models/user.py). По умолчанию 1 для
    новых пользователей; для УЖЕ существующих пользователей нужно
    проставить корректное значение отдельным data-миграционным скриптом
    (см. ниже upgrade()) — иначе следующее добавленное устройство у
    пользователя с уже существующими устройствами получит device_number,
    который может пересечься с уже занятыми.
  - devices.device_number      — порядковый номер устройства пользователя
    (1, 2, 3, ...), используется для построения remote_id клиента в
    панелях 3X-UI (см. app/providers/xui/client.py::remote_id_for).

ВАЖНО: после апгрейда у устройств, созданных ДО этой миграции,
device_number будет NULL. Это не ломает работу (remote_id_for падает на
фоллбэк device.id), но их remote_id в панелях не будет соответствовать
новому формату "{tid}_device_{N}" (там уже есть client с прежним именем
"device_{uuid}") — переименовывать существующих клиентов в панелях нужно
только если это принципиально важно; функционально ничего не сломается.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_device_numbering"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("next_device_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "devices",
        sa.Column("device_number", sa.Integer(), nullable=True),
    )

    # Data-миграция: для уже существующих пользователей проставляем
    # device_number по порядку создания устройства (id ASC) и
    # выставляем next_device_number = count(devices) + 1, чтобы новое
    # устройство не пересеклось по номеру с уже существующими.
    connection = op.get_bind()

    users = connection.execute(sa.text("SELECT id FROM users")).fetchall()
    for (user_id,) in users:
        devices = connection.execute(
            sa.text("SELECT id FROM devices WHERE user_id = :uid ORDER BY id ASC"),
            {"uid": user_id},
        ).fetchall()

        for number, (device_id,) in enumerate(devices, start=1):
            connection.execute(
                sa.text("UPDATE devices SET device_number = :n WHERE id = :did"),
                {"n": number, "did": device_id},
            )

        connection.execute(
            sa.text("UPDATE users SET next_device_number = :n WHERE id = :uid"),
            {"n": len(devices) + 1, "uid": user_id},
        )


def downgrade() -> None:
    op.drop_column("devices", "device_number")
    op.drop_column("users", "next_device_number")
