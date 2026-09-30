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

    # Who the piece is for. Previously stranded in the EAV product_attributes
    # tables that H-06 deletes.
    gender_id = Column(Integer, ForeignKey("genders.id"), nullable=True)

    # Lookup-backed status. The `status` enum above is kept in sync for now and
    # removed once every reader uses status_id.
    status_id = Column(Integer, ForeignKey("product_statuses.id"), nullable=True)

    # Soft delete. Separate from `status` and from is_visible_on_website:
    # `archived` used to mean both "deleted" and "not shown", which made
    # "list deleted products" and "restore this" ambiguous. A timestamp also
    # records WHEN, which an enum cannot.
    deleted_at = Column(TIMESTAMP, nullable=True)

    featured = Column(Boolean, default=False)

    customizable = Column(Boolean, default=False)

    is_visible_on_website = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(TIMESTAMP, server_default=func.now())

    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    subcategory = relationship("Subcategory")
    gender = relationship("Gender")
    product_status = relationship("ProductStatus")
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

    # J-01: passthrough for the storefront's size picker — the subcategory is
    # the one source of truth for what this product's size dimension is called.
    @property
    def size_label(self) -> str | None:
        return self.subcategory.size_label if self.subcategory else None

    @property
    def size_unit(self) -> str | None:
        return self.subcategory.size_unit if self.subcategory else None

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