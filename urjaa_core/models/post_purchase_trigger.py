"""SQLAlchemy model for post-purchase trigger queue."""
import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class PostPurchaseTrigger(Base):
    __tablename__ = "post_purchase_triggers"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('rating_request','review_request','reorder_reminder')",
            name="chk_ppt_trigger_type",
        ),
        CheckConstraint(
            "channel IN ('whatsapp','email')",
            name="chk_ppt_channel",
        ),
        CheckConstraint(
            "status IN ('pending','sent','failed','skipped')",
            name="chk_ppt_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    trigger_type = Column(String(30), nullable=False)
    channel = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=False)
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="post_purchase_triggers")
    user = relationship("User")
