from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AppointmentStatus = Literal["Confirmed", "Rescheduled", "Completed", "Cancelled", "No Show"]


class AppointmentCreateRequest(BaseModel):
    service_type: str = Field(min_length=1, max_length=50)
    store_location_id: UUID
    appointment_date: date
    appointment_time: str = Field(min_length=1, max_length=64)
    guests: int = Field(default=1, ge=1)
    note: str | None = Field(default=None, max_length=5000)


class AppointmentRescheduleRequest(BaseModel):
    appointment_date: date
    appointment_time: str = Field(min_length=1, max_length=64)


class AppointmentResponse(BaseModel):
    id: UUID
    type: str
    showroom: str
    date: date
    time: str
    guests: int
    reference: str
    status: AppointmentStatus
    advisor: str | None
    note: str | None


class AppointmentsResponse(BaseModel):
    items: list[AppointmentResponse]
