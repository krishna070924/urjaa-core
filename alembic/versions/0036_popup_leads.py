"""Offer popup leads on newsletter_subscribers

Columns only (no new table, so no GRANT needed -- INDEX C18): optional
WhatsApp opt-in with phone, sign-up source, and a snapshot of the consent
text the person agreed to.

Revision ID: 0036_popup_leads
Revises: 0035_old_gold_exchange
Create Date: 2026-10-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0036_popup_leads"
down_revision = "0035_old_gold_exchange"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("newsletter_subscribers", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column(
        "newsletter_subscribers",
        sa.Column("whatsapp_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "newsletter_subscribers",
        sa.Column("source", sa.String(20), nullable=False, server_default="footer"),
    )
    op.add_column("newsletter_subscribers", sa.Column("consent_text", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in ("consent_text", "source", "whatsapp_opt_in", "phone"):
        op.drop_column("newsletter_subscribers", column)
