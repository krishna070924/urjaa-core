import uuid

from sqlalchemy import Column, Integer, ForeignKey, DECIMAL, TIMESTAMP, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    quantity = Column(Integer, nullable=False)
    total_amount = Column(DECIMAL(12, 2), nullable=False, default=0, server_default="0")
    final_price = Column(DECIMAL(12, 2), nullable=False)
    cost_price = Column(DECIMAL(12, 2), nullable=False)
    profit = Column(DECIMAL(12, 2), nullable=False)
    source = Column(String(20), nullable=False, default="store", server_default="store")
    status = Column(String(20), nullable=False, default="COMPLETED", server_default="COMPLETED")
    date_time = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    product = relationship("Product")
    variant = relationship("ProductVariant")
    customer = relationship("User", back_populates="sales")
    store = relationship("Store")
    order = relationship("Order", back_populates="sale")
