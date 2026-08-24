"""lab_reports asset_ids to text

Revision ID: c2b989a137d4
Revises: 9d05267ccccd
Create Date: 2026-08-19 11:44:22.451463

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2b989a137d4'
down_revision: Union[str, None] = '9d05267ccccd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite: the original ARRAY(String).with_variant(Text, "sqlite") already stores this
    # column as plain TEXT there — nothing to alter. Postgres has a real array column that
    # needs converting to the JSON-encoded string application code now expects.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "lab_reports",
            "asset_ids",
            type_=sa.Text(),
            postgresql_using="array_to_json(asset_ids)::text",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "lab_reports",
            "asset_ids",
            type_=sa.ARRAY(sa.String()),
            postgresql_using="array(select json_array_elements_text(asset_ids::json))",
        )
