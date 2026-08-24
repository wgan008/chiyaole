"""add explicit_times to medications

Revision ID: 9d05267ccccd
Revises: 2ca6d9cd10ef
Create Date: 2026-08-18 15:36:11.675389

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d05267ccccd'
down_revision: Union[str, None] = '2ca6d9cd10ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("medications", sa.Column("explicit_times", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("medications", "explicit_times")
