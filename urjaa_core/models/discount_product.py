from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from urjaa_core.models.base import Base


class DiscountProduct(Base):
    """Which products a non-store-wide discount applies to (D28/D29)."""

    __tablename__ = "discount_products"

    discount_id = Column(Integer, ForeignKey("discounts.id", ondelete="CASCADE"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
