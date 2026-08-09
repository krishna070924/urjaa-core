from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class AttributeValue(Base):
    __tablename__ = "attribute_values"

    id = Column(Integer, primary_key=True)

    attribute_id = Column(Integer, ForeignKey("attributes.id"))

    value = Column(String(100))

    attribute = relationship("Attribute", back_populates="values")

    products = relationship("ProductAttribute", back_populates="attribute_value")