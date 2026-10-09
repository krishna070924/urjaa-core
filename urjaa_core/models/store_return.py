"""Store returns, credit notes, store credit ledger, old-jewellery exchange
(migrations 0034/0035). Store (POS) bills only."""

from sqlalchemy import DECIMAL, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class SaleReturn(Base):
    __tablename__ = "sale_returns"

    id = Column(Integer, primary_key=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    credit_note_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(String(20), nullable=False)  # defect / size / changed_mind / exchange / other
    reason_note = Column(Text, nullable=True)
    taxable_value = Column(DECIMAL(12, 2), nullable=False)
    cgst = Column(DECIMAL(12, 2), nullable=False)
    sgst = Column(DECIMAL(12, 2), nullable=False)
    deduction_amount = Column(DECIMAL(12, 2), nullable=False, default=0)
    deduction_reason = Column(Text, nullable=True)
    refund_amount = Column(DECIMAL(12, 2), nullable=False)
    refund_method = Column(String(15), nullable=False)  # cash / upi / card / store_credit
    refund_reference = Column(String(100), nullable=True)
    created_by_admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    order = relationship("Order")
    customer = relationship("User")
    lines = relationship("SaleReturnLine", back_populates="sale_return", order_by="SaleReturnLine.id")


class SaleReturnLine(Base):
    __tablename__ = "sale_return_lines"

    id = Column(Integer, primary_key=True)
    return_id = Column(Integer, ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    taxable_value = Column(DECIMAL(12, 2), nullable=False)
    pieces = Column(JSONB, nullable=False, default=list)  # HUID/serial of each returned piece

    sale_return = relationship("SaleReturn", back_populates="lines")
    sale = relationship("Sale")


class StoreCreditEntry(Base):
    """+ from a return (or an old-jewellery payout), - when used on a bill."""

    __tablename__ = "store_credit_entries"

    id = Column(Integer, primary_key=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    amount = Column(DECIMAL(12, 2), nullable=False)
    sale_return_id = Column(Integer, ForeignKey("sale_returns.id"), nullable=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_by_admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)


class OldGoldItem(Base):
    __tablename__ = "old_gold_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(200), nullable=False)
    base_metal_id = Column(Integer, ForeignKey("base_metals.id"), nullable=False)
    purity = Column(DECIMAL(6, 3), nullable=False)  # percent
    gross_weight = Column(DECIMAL(10, 3), nullable=False)
    stone_weight = Column(DECIMAL(10, 3), nullable=False, default=0)
    net_weight = Column(DECIMAL(10, 3), nullable=False)
    rate_per_gram = Column(DECIMAL(12, 2), nullable=False)
    deduction_amount = Column(DECIMAL(12, 2), nullable=False, default=0)
    deduction_reason = Column(Text, nullable=True)
    value = Column(DECIMAL(12, 2), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    base_metal = relationship("BaseMetal")
