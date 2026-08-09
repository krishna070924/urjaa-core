from sqlalchemy import Column, Integer, String
from urjaa_core.models.base import Base


class MetalColor(Base):
    __tablename__ = "metal_colors"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)