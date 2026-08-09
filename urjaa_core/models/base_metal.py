from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class BaseMetal(Base):
    __tablename__ = "base_metals"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)

    purities = relationship("MetalPurity", back_populates="base_metal")