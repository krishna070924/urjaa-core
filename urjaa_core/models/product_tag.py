from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from .base import Base


class ProductTag(Base):
    __tablename__ = "product_tags"
    __table_args__ = (
        UniqueConstraint("product_id", "tag_id", name="uq_product_tags_product_tag"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(ForeignKey("products.id"))
    tag_id = Column(ForeignKey("tags.id"))