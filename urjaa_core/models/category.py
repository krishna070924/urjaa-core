from sqlalchemy import Boolean, Column, Integer, String, text
from urjaa_core.models.base import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    slug = Column(String(120), unique=True, nullable=False)

    display_order = Column(Integer)

    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    is_deleted = Column(Boolean, nullable=False, default=False, server_default=text("false"))