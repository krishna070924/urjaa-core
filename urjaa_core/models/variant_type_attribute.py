from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class VariantTypeAttribute(Base):
    __tablename__ = "variant_type_attributes"

    id = Column(Integer, primary_key=True)

    variant_type_id = Column(Integer, ForeignKey("variant_types.id"), index=True)
    attribute_id = Column(Integer, ForeignKey("attributes.id"), index=True)

    variant_type = relationship("VariantType", back_populates="attributes")
    attribute = relationship("Attribute")
