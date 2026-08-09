import uuid

from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, TIMESTAMP, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR

from urjaa_core.models.base import Base



class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name = Column(String(200), nullable=False)

    slug = Column(String(220), unique=True, nullable=False)

    description = Column(Text)

    subcategory_id = Column(Integer, ForeignKey("subcategories.id"))

    status = Column(
        Enum("draft", "active", "hidden", "archived", name="product_status", create_type=False),
        default="draft",
    )

    featured = Column(Boolean, default=False)

    customizable = Column(Boolean, default=False)

    is_visible_on_website = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(TIMESTAMP, server_default=func.now())

    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    subcategory = relationship("Subcategory")
    store = relationship("Store")

    variants = relationship("ProductVariant", back_populates="product")

    stones = relationship("ProductStone", back_populates="product")

    attributes = relationship("ProductAttribute", back_populates="product")

    collections = relationship("Collection", secondary="product_collections", 
                               back_populates="products")
    
    tags = relationship("Tag", secondary="product_tags", 
                        back_populates="products")
    
    images = relationship("ProductImage", back_populates="product")

    search_vector = Column(TSVECTOR)

    @property
    def category_id(self) -> int | None:
        if self.subcategory is None:
            return None

        return self.subcategory.category_id

    @property
    def collection_id(self) -> int | None:
        if not self.collections:
            return None

        ordered_collections = sorted(
            self.collections,
            key=lambda collection: (
                collection.display_order is None,
                collection.display_order if collection.display_order is not None else 0,
                collection.id,
            ),
        )
        return ordered_collections[0].id