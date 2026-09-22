from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class VariantType(Base):
    __tablename__ = "variant_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(150), unique=True, nullable=False)
    description = Column(Text)
    display_order = Column(Integer)

    attributes = relationship("VariantTypeAttribute", back_populates="variant_type")
