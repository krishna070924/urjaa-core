import uuid

from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class LegalPage(Base):
    __tablename__ = "legal_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(
        Enum("terms", "privacy", "shipping", "returns", "faq", "about", name="legal_page_key"),
        nullable=False,
        unique=True,
        index=True,
    )
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    last_updated = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_by = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True, index=True)
