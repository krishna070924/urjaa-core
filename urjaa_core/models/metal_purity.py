from sqlalchemy import Column, Integer, String, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class MetalPurity(Base):
    __tablename__ = "metal_purities"

    id = Column(Integer, primary_key=True)

    base_metal_id = Column(Integer, ForeignKey("base_metals.id"))

    purity_label = Column(String(20))
    numeric_purity = Column(DECIMAL(5, 3))

    base_metal = relationship("BaseMetal", back_populates="purities")