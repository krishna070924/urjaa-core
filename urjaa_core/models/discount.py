from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Discount(Base):
    """A percentage-off discount, optionally windowed by date (D27-D29).

    Reduces the WHOLE computed product price (metal + stones + making, or
    price_override when set) -- see PricingService.price_variant. Applies
    either to every product in the store (applies_to_all) or to the specific
    products listed in discount_products.
    """

    __tablename__ = "discounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name = Column(String(120), nullable=False)
    percent = Column(Numeric(5, 2), nullable=False)
    starts_at = Column(TIMESTAMP(timezone=True), nullable=True)
    ends_at = Column(TIMESTAMP(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    applies_to_all = Column(Boolean, nullable=False, default=False)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    store = relationship("Store")
    products = relationship("Product", secondary="discount_products")
