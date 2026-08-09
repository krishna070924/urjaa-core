import uuid

from sqlalchemy import Column, ForeignKey, Integer, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class SearchEvent(Base):
    __tablename__ = "search_events"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id           = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id            = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id         = Column(Text, nullable=False, index=True)
    query              = Column(Text, nullable=False)
    result_count       = Column(Integer, nullable=False, default=0)
    clicked_product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    searched_at        = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    clicked_product = relationship("Product", foreign_keys=[clicked_product_id])
    user            = relationship("User", foreign_keys=[user_id])
