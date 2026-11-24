"""Add protocol selection to Agent credentials."""

from alembic import op
import sqlalchemy as sa

revision = "c713a82f9021"
down_revision = "b793a01c4e62"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_anthropic_credentials", sa.Column("protocol", sa.String(16), nullable=False, server_default="anthropic"))


def downgrade():
    op.drop_column("agent_anthropic_credentials", "protocol")
