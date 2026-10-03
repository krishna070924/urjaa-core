from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Karigar(Base):
    """O-04/D44: an artisan a custom order can be assigned to. Store-scoped,
    managed from admin Configuration."""

    __tablename__ = "karigars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name = Column(String(120), nullable=False)
    phone = Column(String(15), nullable=False)
    speciality = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    store = relationship("Store")
