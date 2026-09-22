from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class VariantAttribute(Base):
    __tablename__ = "variant_attributes"
    __table_args__ = (
        UniqueConstraint("variant_id", "attribute_value_id", name="uq_variant_attributes_variant_attribute_value"),
    )

    id = Column(Integer, primary_key=True)

    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id"), index=True)
    attribute_value_id = Column(Integer, ForeignKey("attribute_values.id"), index=True)

    variant = relationship("ProductVariant", back_populates="attribute_values")

    attribute_value = relationship(
        "AttributeValue",
        back_populates="variant_attributes"
    )
