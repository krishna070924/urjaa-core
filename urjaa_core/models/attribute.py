from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Attribute(Base):
    __tablename__ = "attributes"

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    slug = Column(String(120))
    filterable = Column(Boolean, default=True)

    values = relationship("AttributeValue", back_populates="attribute")