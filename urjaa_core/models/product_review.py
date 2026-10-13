import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class ProductReview(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="chk_reviews_rating_range"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    rating = Column(Integer, nullable=False)
    title = Column(String(150), nullable=True)
    content = Column(Text, nullable=False)
    is_verified_purchase = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    is_approved = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    # UX-12 (D10: publish immediately, moderate after). Hidden = is_approved
    # False. Delete is soft (deleted_at) so the record stays for audit.
    moderated_at = Column(TIMESTAMP, nullable=True)
    moderated_by_admin_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = Column(TIMESTAMP, nullable=True, index=True)
    # One staff reply per review, plain text.
    reply_content = Column(Text, nullable=True)
    replied_at = Column(TIMESTAMP, nullable=True)
    replied_by_admin_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
