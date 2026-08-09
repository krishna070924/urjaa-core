import uuid

from sqlalchemy import Column, Enum, ForeignKey, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider = Column(
        Enum("razorpay", name="payment_provider"),
        nullable=False,
        default="razorpay",
        server_default="razorpay",
        index=True,
    )
    provider_order_id = Column(String(100), nullable=True, index=True)
    provider_payment_id = Column(String(100), nullable=True, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="INR", server_default="INR")
    status = Column(
        Enum("created", "paid", "failed", "refunded", name="payment_transaction_status"),
        nullable=False,
        default="created",
        server_default="created",
        index=True,
    )
    raw_response = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
