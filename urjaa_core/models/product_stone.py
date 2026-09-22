from sqlalchemy import Column, Integer, ForeignKey, DECIMAL, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from urjaa_core.models.base import Base


class ProductStone(Base):
    __tablename__ = "product_stones"
    __table_args__ = (
        UniqueConstraint("product_id", "stone_id", name="uq_product_stones_product_stone"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), index=True)
    stone_id = Column(Integer, ForeignKey("stones.id"))
    quantity = Column(Integer)
    total_carat_weight = Column(DECIMAL(10, 3))

    product = relationship("Product", back_populates="stones")
    stone = relationship("Stone", back_populates="products")