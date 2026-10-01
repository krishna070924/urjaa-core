from sqlalchemy import Column, Integer, Numeric, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=False)

    product_name = Column(String(255), nullable=True)
    product_image = Column(Text, nullable=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)

    # K-03: discount audit snapshot. Null when the line had no discount applied.
    # unit_price above is already the discounted (final) price actually charged.
    original_unit_price = Column(Numeric(12, 2), nullable=True)
    discount_percent = Column(Numeric(5, 2), nullable=True)

    order = relationship("Order", back_populates="items")
    store = relationship("Store")
    product = relationship("Product")
    variant = relationship("ProductVariant")

    # H-03/H-05: the physical piece(s) (D22) this line reserved or sold, if the
    # variant is tracked piece-by-piece. Untracked variants: always empty.
    # viewonly — physical_unit_service owns writes via order_item_id.
    physical_units = relationship(
        "VariantPhysicalUnit",
        primaryjoin="OrderItem.id==VariantPhysicalUnit.order_item_id",
        viewonly=True,
    )

    @property
    def huid_numbers(self) -> list[str]:
        """HUIDs of this line's reserved/sold piece(s). Staff-only (admin
        schemas only) — not on the storefront-facing OrderItemResponse."""
        return [unit.huid_number for unit in self.physical_units if unit.huid_number]
