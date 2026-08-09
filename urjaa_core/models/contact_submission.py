import uuid

from sqlalchemy import Column, Enum, ForeignKey, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    message = Column(Text, nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)
    status = Column(
        Enum("new", "read", "replied", name="contact_submission_status"),
        nullable=False,
        default="new",
        server_default="new",
        index=True,
    )
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
