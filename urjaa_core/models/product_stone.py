from sqlalchemy import CheckConstraint, Column, Integer, ForeignKey, DECIMAL, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from urjaa_core.models.base import Base

# B-02: certification agencies the storefront's GemstoneSpec union type
# accepts (urjaa-storefront/src/types/product.ts). Kept in sync with the
# `chk_product_stones_certification_agency` DB constraint below.
CERTIFICATION_AGENCIES = ("GIA", "IGI", "HRD", "BIS")


class ProductStone(Base):
    __tablename__ = "product_stones"
    __table_args__ = (
        UniqueConstraint("product_id", "stone_id", name="uq_product_stones_product_stone"),
        CheckConstraint(
            "certification_agency IN ('GIA', 'IGI', 'HRD', 'BIS')",
            name="chk_product_stones_certification_agency",
        ),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), index=True)
    stone_id = Column(Integer, ForeignKey("stones.id"))
    quantity = Column(Integer)
    total_carat_weight = Column(DECIMAL(10, 3))

    # B-02 (D4): hand-entered certification, per-stone-on-this-product — not on
    # `stones` (that's a shared name lookup) or `products` (a piece can carry
    # several separately-certified stones). All nullable (D3): never required
    # to create a product or variant.
    cut = Column(String(50))
    clarity = Column(String(20))
    color = Column(String(20))
    origin = Column(String(100))
    certificate_number = Column(String(100))
    certification_agency = Column(String(10))

    product = relationship("Product", back_populates="stones")
    stone = relationship("Stone", back_populates="products")

    @property
    def name(self) -> str | None:
        """Stone name for storefront display (from the related Stone)."""
        return self.stone.name if self.stone else None