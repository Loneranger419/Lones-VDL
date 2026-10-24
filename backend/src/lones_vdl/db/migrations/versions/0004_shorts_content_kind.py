"""shorts content kind

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 20:04:23.013677

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Existing attempts have no kind and count as videos."""
    with op.batch_alter_table("access_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_kind", sa.String(length=20), nullable=True))

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("content_kind")

    with op.batch_alter_table("access_attempts", schema=None) as batch_op:
        batch_op.drop_column("content_kind")
