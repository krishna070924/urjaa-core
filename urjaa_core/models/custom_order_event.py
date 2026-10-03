from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base

CUSTOM_ORDER_EVENT_KINDS = ("created", "status", "karigar", "edit")


class CustomOrderEvent(Base):
    """O-04/D44: audit trail entry for a custom order -- who did what, when.
    One row per creation, status move, karigar assignment, or field edit."""

    __tablename__ = "custom_order_events"
    __table_args__ = (
        CheckConstraint("kind IN ('created', 'status', 'karigar', 'edit')", name="ck_custom_order_events_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("custom_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    by_admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    kind = Column(String(30), nullable=False)
    from_value = Column(String(120), nullable=True)
    to_value = Column(String(120), nullable=True)
    note = Column(Text, nullable=True)

    order = relationship("CustomOrder", back_populates="events")
    by_admin = relationship("AdminUser", foreign_keys=[by_admin_id])
