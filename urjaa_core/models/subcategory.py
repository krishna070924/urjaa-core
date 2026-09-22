from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Subcategory(Base):
    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True)

    category_id = Column(Integer, ForeignKey("categories.id"))

    name = Column(String(120), nullable=False)

    slug = Column(String(150), unique=True, nullable=False)

    default_variant_type_id = Column(Integer, ForeignKey("variant_types.id"), nullable=True)

    category = relationship("Category")
    default_variant_type = relationship("VariantType")