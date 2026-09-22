from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint

from .base import Base


class ProductCollection(Base):
    __tablename__ = "product_collections"
    __table_args__ = (
        UniqueConstraint("product_id", "collection_id", name="uq_product_collections_product_collection"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("products.id"))
    collection_id = Column(ForeignKey("collections.id"))