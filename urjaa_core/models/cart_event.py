import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Numeric, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class CartEvent(Base):
    __tablename__ = "cart_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('add', 'remove', 'checkout_started', 'checkout_abandoned')",
            name="chk_cart_events_type",
        ),
    )

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id       = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id     = Column(Text, nullable=False, index=True)
    product_id     = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id     = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    event_type     = Column(Text, nullable=False)
    quantity       = Column(Integer, nullable=False, default=1)
    price_at_event = Column(Numeric(12, 2), nullable=True)
    occurred_at    = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    product = relationship("Product", foreign_keys=[product_id])
    user    = relationship("User", foreign_keys=[user_id])
