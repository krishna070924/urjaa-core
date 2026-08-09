from sqlalchemy import Column, Integer, ForeignKey
from .base import Base


class ProductTag(Base):
    __tablename__ = "product_tags"

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("products.id"))
    tag_id = Column(ForeignKey("tags.id"))