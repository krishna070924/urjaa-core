import uuid

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DECIMAL
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), index=True)

    base_metal_id = Column(Integer, ForeignKey("base_metals.id"))
    metal_color_id = Column(Integer, ForeignKey("metal_colors.id"))
    metal_purity_id = Column(Integer, ForeignKey("metal_purities.id"))

    weight = Column(DECIMAL(10, 3))
    metal_type = Column(String(50))
    metal_weight_grams = Column(DECIMAL(10, 3))
    stone_quantity = Column(Integer, default=0)
    stone_cost = Column(DECIMAL(10, 2), default=0)
    making_charges = Column(DECIMAL(10, 2))
    cost_price = Column(DECIMAL(10, 2), default=0)
    price_override = Column(DECIMAL(10, 2))

    stock_quantity = Column(Integer, default=0)
    sku_code = Column(String(100), unique=True)

    status = Column(String(20), default="active")

    # Staff-only: physical stock location notes (e.g. "box 4, shelf B").
    # Never exposed via storefront-facing schemas.
    internal_notes = Column(Text, nullable=True)

    # BIS hallmark ID; optional, one per variant (see ticket for per-piece caveat).
    huid_number = Column(String(50), nullable=True)

    product = relationship("Product", back_populates="variants")
    store = relationship("Store")

    base_metal = relationship("BaseMetal")
    metal_color = relationship("MetalColor")
    metal_purity = relationship("MetalPurity")

    attribute_values = relationship("VariantAttribute", back_populates="variant")

    @property
    def attribute_label(self) -> str | None:
        """Display label built from this variant's attribute values, e.g.
        "Ring Size 6, Ruby". None if the variant has no attribute values
        (replaces the old, now-dropped `size` column for display purposes).
        """
        values = [
            va.attribute_value.value
            for va in self.attribute_values
            if va.attribute_value and va.attribute_value.value
        ]
        return ", ".join(values) if values else None