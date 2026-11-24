"""Add extra ComfyUI addresses to custom providers."""

import sqlalchemy as sa
from alembic import op

revision = "d04e9a317b62"
down_revision = "c713a82f9021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("custom_provider", sa.Column("extra_base_urls", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("custom_provider", "extra_base_urls")
