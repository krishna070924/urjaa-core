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

    # D21: the single variation dimension. Text, not numeric — ring sizes,
    # lengths in inches and diameters in mm are not one number type. What this
    # value is CALLED lives on the subcategory (size_label / size_unit).
    size_value = Column(String(50), nullable=True)

    # Escape hatch for one-off descriptors. Display-only, never filtered on.
    # Deliberately not a second attribute system.
    spec_note = Column(String(200), nullable=True)

    product = relationship("Product", back_populates="variants")
    store = relationship("Store")

    base_metal = relationship("BaseMetal")
    metal_color = relationship("MetalColor")
    metal_purity = relationship("MetalPurity")

    attribute_values = relationship("VariantAttribute", back_populates="variant")

    @property
    def attribute_label(self) -> str | None:
        """Display label for this variant's variation, e.g. "Ring Size 6" or
        "Length 18 inches".

        Derived from `size_value` plus the owning subcategory's `size_label`
        and `size_unit` (decision D21). Falls back to the bare value when the
        subcategory has no label configured, and returns None when the variant
        has no size at all.

        The API field name stays `attribute_label` so storefront clients do not
        break; only what feeds it changed.
        """
        value = (self.size_value or "").strip()
        if not value:
            return None

        subcategory = getattr(getattr(self, "product", None), "subcategory", None)
        label = (getattr(subcategory, "size_label", None) or "").strip()
        unit = (getattr(subcategory, "size_unit", None) or "").strip()

        parts = [part for part in (label, value, unit) if part]
        return " ".join(parts)
