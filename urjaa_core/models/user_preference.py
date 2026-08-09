from sqlalchemy import CheckConstraint, Column, ForeignKey, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("theme IN ('ivory', 'obsidian')", name="chk_user_preferences_theme"),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme = Column(String(16), nullable=False, server_default=text("'obsidian'"))
    wishlist = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    recently_viewed = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    preferred_categories = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="preferences")