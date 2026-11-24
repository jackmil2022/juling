"""Wait for neighboring video jobs without cascading their failure."""

import sqlalchemy as sa
from alembic import op

revision = "e73a95d204bf"
down_revision = "b42ad6e7c311"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("previous_video_task_id", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("next_video_task_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "next_video_task_id")
    op.drop_column("tasks", "previous_video_task_id")
