from sqlalchemy import Column, Integer, ForeignKey

from .base import Base


class ProductCollection(Base):
    __tablename__ = "product_collections"

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("products.id"))
    collection_id = Column(ForeignKey("collections.id"))