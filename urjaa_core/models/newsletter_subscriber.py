import uuid

from sqlalchemy import Boolean, Column, String, Text, TIMESTAMP, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscribers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    subscribed_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    unsubscribed_at = Column(TIMESTAMP, nullable=True)
    # Offer popups: optional WhatsApp opt-in (phone kept only when ticked),
    # where they signed up, and the exact text they agreed to (DPDP proof).
    phone = Column(String(20), nullable=True)
    whatsapp_opt_in = Column(Boolean, nullable=False, server_default=false())
    source = Column(String(20), nullable=False, server_default="footer")
    consent_text = Column(Text, nullable=True)
