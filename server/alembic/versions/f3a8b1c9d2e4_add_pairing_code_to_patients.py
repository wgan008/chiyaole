"""add pairing_code to patients

Revision ID: f3a8b1c9d2e4
Revises: c2b989a137d4
Create Date: 2026-08-21 09:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a8b1c9d2e4'
down_revision: str | None = 'c2b989a137d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table: SQLite (this repo's dev backend) has no ALTER TABLE ADD CONSTRAINT
    # — alembic emulates it there via a rebuild-the-table batch op; on Postgres (spec: prod
    # is always Postgres 16) the same call compiles straight to a real ALTER TABLE.
    with op.batch_alter_table("patients") as batch_op:
        batch_op.add_column(sa.Column("pairing_code", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("pairing_code_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint("uq_patients_pairing_code", ["pairing_code"])


def downgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_constraint("uq_patients_pairing_code", type_="unique")
        batch_op.drop_column("pairing_code_expires_at")
        batch_op.drop_column("pairing_code")
