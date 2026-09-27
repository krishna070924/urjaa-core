import uuid

from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base

# F-01: showroom-visit booking. Distinct from CommissionRequest, which models
# custom-design commissions (no showroom, no service type, no reschedule, no
# "No Show" status) — see docs/frontend-transition-to-2.0/slice-F-appointments.
#
# D9: the storefront's mock (urjaa-storefront/src/lib/appointments.ts) is the
# spec for both the service-type vocabulary (book-appointment/page.tsx SERVICES
# names) and the status vocabulary (StatusBadge.tsx).
SERVICE_TYPES = (
    "Jewellery Consultation",
    "Bridal Consultation",
    "Custom Design Consultation",
    "High Jewellery Viewing",
    "Collection Viewing",
)

APPOINTMENT_STATUSES = ("Confirmed", "Rescheduled", "Completed", "Cancelled", "No Show")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Confirmed', 'Rescheduled', 'Completed', 'Cancelled', 'No Show')",
            name="chk_appointments_status_allowed",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    store_location_id = Column(
        UUID(as_uuid=True), ForeignKey("store_locations.id"), nullable=False, index=True
    )

    service_type = Column(String(50), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(String(64), nullable=False)  # free-form slot text, e.g. "4:30 PM" (D19: no slot inventory)
    guests = Column(Integer, nullable=False, default=1, server_default="1")
    reference = Column(String(20), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="Confirmed", server_default="Confirmed", index=True)
    advisor = Column(String(120), nullable=True)  # assigned by staff in admin; never set at creation
    note = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")
    store_location = relationship("StoreLocation")
