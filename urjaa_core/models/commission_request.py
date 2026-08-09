import uuid

from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class CommissionRequest(Base):
    __tablename__ = "commission_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'rescheduled')",
            name="chk_commission_requests_status_allowed",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    preferred_date = Column(Date, nullable=False)
    preferred_time = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    reference_images = Column(JSONB, nullable=False, default=list, server_default="[]")
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    admin_notes = Column(Text, nullable=True)
    final_date = Column(Date, nullable=True)
    final_time = Column(String(64), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")
