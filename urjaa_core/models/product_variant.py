import uuid

from sqlalchemy import (
    Column,
    Integer,
    String,
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

    size = Column(String(20))

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

    product = relationship("Product", back_populates="variants")
    store = relationship("Store")

    base_metal = relationship("BaseMetal")
    metal_color = relationship("MetalColor")
    metal_purity = relationship("MetalPurity")