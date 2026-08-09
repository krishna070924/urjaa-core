import uuid

from sqlalchemy import CheckConstraint, Column, Enum, Integer, String, TIMESTAMP, Numeric, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base
from urjaa_core.utils.currency import format_inr


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED')",
            name="chk_orders_status_allowed",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    email = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=False)
    phone = Column(String(50), nullable=True)
    shipping_address = Column(JSONB, nullable=False, default=dict)

    total_amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR", server_default="INR")
    payment_status = Column(
        Enum("unpaid", "paid", "refunded", name="order_payment_status"),
        nullable=False,
        default="unpaid",
        server_default="unpaid",
        index=True,
    )
    status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    cancelled_at = Column(TIMESTAMP, nullable=True)

    # Post-purchase rating fields
    customer_rating = Column(Integer, nullable=True)
    rating_comment = Column(Text, nullable=True)
    rated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    store = relationship("Store")
    user = relationship("User")
    sale = relationship("Sale", back_populates="order", uselist=False)
    post_purchase_triggers = relationship("PostPurchaseTrigger", back_populates="order")

    @property
    def formatted_total(self) -> str:
        return format_inr(self.total_amount or 0)
