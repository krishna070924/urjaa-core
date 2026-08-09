from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Stone(Base):
    __tablename__ = "stones"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    products = relationship("ProductStone", back_populates="stone")