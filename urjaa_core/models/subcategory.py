from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Subcategory(Base):
    __tablename__ = "subcategories"

    id = Column(Integer, primary_key=True)

    category_id = Column(Integer, ForeignKey("categories.id"))

    name = Column(String(120), nullable=False)

    slug = Column(String(150), unique=True, nullable=False)

    # D21: what this category's single variation dimension is called, and in
    # what unit — e.g. ("Length", "inches"), ("Ring Size", "US"),
    # ("Diameter", "mm"). Both null means this category does not vary by size,
    # and the admin hides the field entirely rather than showing an empty box.
    size_label = Column(String(50), nullable=True)
    size_unit = Column(String(20), nullable=True)

    category = relationship("Category")