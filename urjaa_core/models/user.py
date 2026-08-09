import uuid

from sqlalchemy import Boolean, Column, Date, ForeignKey, String, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class User(Base):
    __tablename__ = "users"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email            = Column(String(255), nullable=False, unique=True, index=True)
    password_hash    = Column(String(255), nullable=False)
    full_name        = Column(String(200), nullable=False)
    phone            = Column(String(20), nullable=True)
    last_store_id    = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    source           = Column(String(16), nullable=False, default="WEBSITE", server_default="WEBSITE", index=True)
    address          = Column(Text, nullable=True)
    feedback         = Column(Text, nullable=True)
    provider         = Column(String(32), nullable=False, default="local", server_default="local", index=True)
    provider_id      = Column(String(255), nullable=True, index=True)
    is_active        = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at       = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at       = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Analytics & CRM columns (migration 42)
    date_of_birth    = Column(Date, nullable=True)
    whatsapp_number  = Column(String(30), nullable=True)
    whatsapp_opt_in  = Column(Boolean, nullable=False, default=False, server_default="false")
    last_seen_at     = Column(TIMESTAMP(timezone=True), nullable=True, index=True)

    addresses             = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    sales                 = relationship("Sale", back_populates="customer")
    last_store            = relationship("Store", foreign_keys=[last_store_id])
    refresh_tokens        = relationship("UserRefreshToken", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    preferences           = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
