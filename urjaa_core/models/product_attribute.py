from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class ProductAttribute(Base):
    __tablename__ = "product_attributes"
    __table_args__ = (
        UniqueConstraint("product_id", "attribute_value_id", name="uq_product_attributes_product_attribute_value"),
    )

    id = Column(Integer, primary_key=True)

    product_id = Column(ForeignKey("products.id"), index=True)
    attribute_value_id = Column(ForeignKey("attribute_values.id"))

    product = relationship("Product", back_populates="attributes")

    attribute_value = relationship(
        "AttributeValue",
        back_populates="products"
    )