import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(
            "category IN ('order_issue', 'product_query', 'return_request', 'general', 'complaint')",
            name="chk_tickets_category",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="chk_tickets_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'waiting_customer', 'resolved', 'closed')",
            name="chk_tickets_status",
        ),
    )

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id              = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id               = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_submission_id = Column(UUID(as_uuid=True), ForeignKey("contact_submissions.id", ondelete="SET NULL"), nullable=True)
    subject               = Column(Text, nullable=False)
    body                  = Column(Text, nullable=False)
    customer_name         = Column(Text, nullable=False)
    customer_email        = Column(Text, nullable=False)
    customer_phone        = Column(Text, nullable=True)
    category              = Column(Text, nullable=False, default="general", server_default="general")
    priority              = Column(Text, nullable=False, default="normal", server_default="normal")
    status                = Column(Text, nullable=False, default="open", server_default="open")
    assigned_to           = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True, index=True)
    resolved_at           = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at            = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at            = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    replies        = relationship("TicketReply", back_populates="ticket", cascade="all, delete-orphan")
    assigned_admin = relationship("AdminUser", foreign_keys=[assigned_to])
    user           = relationship("User", foreign_keys=[user_id])


class TicketReply(Base):
    __tablename__ = "ticket_replies"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id   = Column(UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id    = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    body        = Column(Text, nullable=False)
    is_internal = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    ticket = relationship("SupportTicket", back_populates="replies")
    admin  = relationship("AdminUser", foreign_keys=[admin_id])
