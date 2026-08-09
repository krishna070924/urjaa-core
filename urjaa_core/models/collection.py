from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .base import Base


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    description = Column(Text)
    banner_image = Column(Text)
    is_featured = Column(Boolean, default=False)
    display_order = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())

    products = relationship(
        "Product",
        secondary="product_collections",
        back_populates="collections"
    )