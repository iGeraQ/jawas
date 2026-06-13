"""rename_tweet_count_to_post_count

Revision ID: b418ff72f986
Revises: d20f82f82541
Create Date: 2026-06-12 20:57:32.547740

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b418ff72f986'
down_revision: Union[str, Sequence[str], None] = 'd20f82f82541'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("published_posts", "tweet_count", new_column_name="post_count")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("published_posts", "post_count", new_column_name="tweet_count")
