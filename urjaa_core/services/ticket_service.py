"""Shared helpers for auto-creating support tickets from storefront submissions.

Extracted from app/api/routes/admin/tickets.py so that non-admin route modules
(commission.py, contact.py) don't need to import from the admin route tree —
admin and storefront routes must have zero cross-imports of each other ahead
of the repo split (see Task 1.2).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from urjaa_core.models.support_ticket import SupportTicket


def auto_create_ticket_from_submission(submission: any, db: Session) -> SupportTicket:
    """Create a SupportTicket linked to a ContactSubmission."""
    ticket = SupportTicket(
        contact_submission_id=submission.id,
        store_id=submission.store_id,
        subject=f"Contact: {submission.name}",
        body=submission.message,
        customer_name=submission.name,
        customer_email=submission.email,
        customer_phone=submission.phone,
        category="general",
        priority="normal",
        status="open",
    )
    db.add(ticket)
    # Note: caller must commit
    return ticket


def auto_create_ticket_from_commission(commission: any, db: Session) -> SupportTicket:
    """Auto-create a support ticket when a commission/appointment request is submitted."""
    subject = f"Appointment Request — {commission.preferred_date} at {commission.preferred_time}"

    body_parts = [
        "A new appointment request has been submitted.",
        "",
        f"Preferred Date: {commission.preferred_date}",
        f"Preferred Time: {commission.preferred_time}",
    ]
    if commission.notes:
        body_parts.append(f"Notes: {commission.notes}")
    if commission.reference_images:
        body_parts.append(f"Reference images: {len(commission.reference_images)} attached")

    body = "\n".join(body_parts)

    user = commission.user
    customer_name = (user.full_name if user and user.full_name else None) or "Customer"
    customer_email = (user.email if user else None) or ""
    customer_phone = getattr(user, "phone", None) if user else None

    ticket = SupportTicket(
        user_id=commission.user_id,
        subject=subject,
        body=body,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        category="general",
        priority="normal",
        status="open",
    )
    db.add(ticket)
    db.flush()
    return ticket
