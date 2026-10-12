"""Review moderation audit, soft delete and one staff reply per review (UX-12)

Columns only on `reviews` (no new table, so no GRANT needed -- INDEX C18).
Hidden stays `is_approved = false`.

Revision ID: 0037_review_moderation_replies
Revises: 0036_popup_leads
Create Date: 2026-10-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0037_review_moderation_replies"
down_revision = "0036_popup_leads"
branch_labels = None
depends_on = None


def _admin_fk() -> sa.ForeignKey:
    return sa.ForeignKey("admin_users.id", ondelete="SET NULL")


def upgrade() -> None:
    op.add_column("reviews", sa.Column("moderated_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("reviews", sa.Column("moderated_by_admin_id", sa.Integer(), _admin_fk(), nullable=True))
    op.add_column("reviews", sa.Column("deleted_at", sa.TIMESTAMP(), nullable=True))
    op.create_index("ix_reviews_deleted_at", "reviews", ["deleted_at"])
    op.add_column("reviews", sa.Column("reply_content", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("replied_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("reviews", sa.Column("replied_by_admin_id", sa.Integer(), _admin_fk(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_reviews_deleted_at", table_name="reviews")
    for column in (
        "replied_by_admin_id", "replied_at", "reply_content",
        "deleted_at", "moderated_by_admin_id", "moderated_at",
    ):
        op.drop_column("reviews", column)
