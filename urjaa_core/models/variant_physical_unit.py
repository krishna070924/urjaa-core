from sqlalchemy import DECIMAL, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class UnitStatus(Base):
    """in_stock / reserved / sold / returned. Only in_stock counts as available."""

    __tablename__ = "unit_statuses"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False, unique=True)


class VariantPhysicalUnit(Base):
    """One physical piece of a variant (D22). BIS assigns a HUID per piece.

    For a variant with unit rows, product_variants.stock_quantity is kept equal
    to its in_stock count by database triggers (migration 0026) — never write
    it expecting it to stick. Variants without units keep a hand-kept count.
    """

    __tablename__ = "variant_physical_units"

    id = Column(Integer, primary_key=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    status_id = Column(Integer, ForeignKey("unit_statuses.id"), nullable=False)
    huid_number = Column(String(50), nullable=True)
    weight_grams = Column(DECIMAL(10, 3), nullable=True)
    location_note = Column(Text, nullable=True)
    # Which online order line reserved it / which in-store sale sold it.
    order_item_id = Column(Integer, ForeignKey("order_items.id", ondelete="SET NULL"), nullable=True)
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id", ondelete="SET NULL"), nullable=True)

    status = relationship("UnitStatus")
    order_item = relationship("OrderItem")
    sale = relationship("Sale")
