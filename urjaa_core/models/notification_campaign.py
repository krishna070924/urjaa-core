import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class NotificationCampaign(Base):
    __tablename__ = "notification_campaigns"
    __table_args__ = (
        CheckConstraint("type IN ('whatsapp', 'email')", name="chk_campaign_type"),
        CheckConstraint(
            "trigger_type IN ('wishlist_reminder', 'cart_abandon', 'reengagement', 'promo_code', 'product_launch', 'manual')",
            name="chk_campaign_trigger_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'sending', 'sent', 'failed')",
            name="chk_campaign_status",
        ),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id         = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by       = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    name             = Column(Text, nullable=False)
    type             = Column(Text, nullable=False)
    trigger_type     = Column(Text, nullable=False)
    template_name    = Column(Text, nullable=False)
    template_params  = Column(JSONB, nullable=False, default=dict, server_default="{}")
    audience_filter  = Column(JSONB, nullable=False, default=dict, server_default="{}")
    scheduled_at     = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_at          = Column(TIMESTAMP(timezone=True), nullable=True)
    status           = Column(Text, nullable=False, default="draft", server_default="draft")
    recipient_count  = Column(Integer, nullable=False, default=0, server_default="0")
    created_at       = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    logs       = relationship("NotificationLog", back_populates="campaign", cascade="all, delete-orphan")
    creator    = relationship("AdminUser", foreign_keys=[created_by])


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'failed', 'opted_out')",
            name="chk_notification_log_status",
        ),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id     = Column(UUID(as_uuid=True), ForeignKey("notification_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    channel         = Column(Text, nullable=False)
    recipient       = Column(Text, nullable=False)
    status          = Column(Text, nullable=False, default="pending", server_default="pending")
    provider_msg_id = Column(Text, nullable=True)
    error_message   = Column(Text, nullable=True)
    sent_at         = Column(TIMESTAMP(timezone=True), nullable=True)
    delivered_at    = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    campaign = relationship("NotificationCampaign", back_populates="logs")
    user     = relationship("User", foreign_keys=[user_id])
