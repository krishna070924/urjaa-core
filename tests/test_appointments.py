"""F-01 self-check: the `appointments` table and its status CHECK constraint.

Proves:
- a normal appointment (Confirmed status, default) commits clean;
- `status` is rejected by `chk_appointments_status_allowed` for values outside
  the storefront's fixed vocabulary (urjaa-storefront/src/lib/appointments.ts);
- the ownership query the storefront-backend routes use (filter by
  `Appointment.id` AND `Appointment.user_id`) returns nothing for a second
  user's appointment -- the exact guard that stops user A from cancelling or
  rescheding user B's booking.

Integration test against the live dev Postgres (DATABASE_URL from env/.env),
same pattern as tests/test_product_stone_certification.py -- no mocking the
ORM, no sqlite. Creates its own throwaway store/store_location/user fixtures
and deletes every row it creates in a `finally` block.

Run: `python tests/test_appointments.py` (DATABASE_URL must already point at
a migrated `urjaa` DB -- run `alembic upgrade head` first).
"""

import os
import sys
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urjaa_core.core.database import SessionLocal  # noqa: E402
from urjaa_core.models.appointment import Appointment  # noqa: E402
from urjaa_core.models.store import Store  # noqa: E402
from urjaa_core.models.store_location import StoreLocation  # noqa: E402
from urjaa_core.models.user import User  # noqa: E402


def _make_user(db, tag: str) -> User:
    user = User(
        id=uuid4(),
        email=f"appt-test-{tag}-{uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        full_name=f"Test User {tag}",
    )
    db.add(user)
    return user


def _cleanup(db, store, location, users, appointment_ids):
    db.rollback()
    if appointment_ids:
        db.query(Appointment).filter(Appointment.id.in_(appointment_ids)).delete(synchronize_session=False)
    for user in users:
        if user is not None:
            db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    if location is not None:
        db.query(StoreLocation).filter(StoreLocation.id == location.id).delete(synchronize_session=False)
    if store is not None:
        db.query(Store).filter(Store.id == store.id).delete(synchronize_session=False)
    db.commit()


def test_appointment_creates_clean_with_default_confirmed_status():
    db = SessionLocal()
    store = location = None
    users: list = []
    appointment_ids: list = []
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)
        db.flush()

        location = StoreLocation(
            id=uuid4(), store_id=store.id, address="1 Test Road", city="Testville", state="TS", pincode="000000"
        )
        db.add(location)

        user = _make_user(db, "a")
        users.append(user)
        db.flush()

        appt = Appointment(
            id=uuid4(),
            user_id=user.id,
            store_location_id=location.id,
            service_type="Jewellery Consultation",
            appointment_date=date.today() + timedelta(days=7),
            appointment_time="4:30 PM",
            guests=2,
            reference=f"URJ-APT-{uuid4().hex[:8].upper()}",
        )
        db.add(appt)
        db.commit()
        appointment_ids.append(appt.id)

        db.refresh(appt)
        assert appt.status == "Confirmed", appt.status
        assert appt.guests == 2
        print("OK: appointment created with default Confirmed status")
    finally:
        _cleanup(db, store, location, users, appointment_ids)
        db.close()


def test_invalid_status_rejected_by_db_constraint():
    db = SessionLocal()
    store = location = None
    users: list = []
    appointment_ids: list = []
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)
        db.flush()
        location = StoreLocation(
            id=uuid4(), store_id=store.id, address="1 Test Road", city="Testville", state="TS", pincode="000000"
        )
        db.add(location)
        user = _make_user(db, "b")
        users.append(user)
        db.flush()

        bad = Appointment(
            id=uuid4(),
            user_id=user.id,
            store_location_id=location.id,
            service_type="Jewellery Consultation",
            appointment_date=date.today() + timedelta(days=7),
            appointment_time="4:30 PM",
            reference=f"URJ-APT-{uuid4().hex[:8].upper()}",
            status="Bogus",
        )
        db.add(bad)
        raised = False
        try:
            db.commit()
        except IntegrityError as exc:
            raised = True
            assert "chk_appointments_status_allowed" in str(exc.orig), exc.orig
        assert raised, "expected IntegrityError for an invalid status"
        print("OK: invalid status rejected by DB constraint")
    finally:
        _cleanup(db, store, location, users, appointment_ids)
        db.close()


def test_ownership_query_excludes_other_users_appointment():
    """The exact guard the storefront-backend cancel/reschedule routes rely
    on: filtering by (id, user_id) together must return nothing for a
    different user's appointment id."""
    db = SessionLocal()
    store = location = None
    users: list = []
    appointment_ids: list = []
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)
        db.flush()
        location = StoreLocation(
            id=uuid4(), store_id=store.id, address="1 Test Road", city="Testville", state="TS", pincode="000000"
        )
        db.add(location)
        user_a = _make_user(db, "owner")
        user_b = _make_user(db, "intruder")
        users.extend([user_a, user_b])
        db.flush()

        appt = Appointment(
            id=uuid4(),
            user_id=user_a.id,
            store_location_id=location.id,
            service_type="Bridal Consultation",
            appointment_date=date.today() + timedelta(days=3),
            appointment_time="11:00 AM",
            reference=f"URJ-APT-{uuid4().hex[:8].upper()}",
        )
        db.add(appt)
        db.commit()
        appointment_ids.append(appt.id)

        owner_hit = (
            db.query(Appointment).filter(Appointment.id == appt.id, Appointment.user_id == user_a.id).first()
        )
        intruder_hit = (
            db.query(Appointment).filter(Appointment.id == appt.id, Appointment.user_id == user_b.id).first()
        )
        assert owner_hit is not None, "owner must be able to find their own appointment"
        assert intruder_hit is None, "a different user must never match another user's appointment id"
        print("OK: ownership-scoped query excludes a different user's appointment")
    finally:
        _cleanup(db, store, location, users, appointment_ids)
        db.close()


if __name__ == "__main__":
    test_appointment_creates_clean_with_default_confirmed_status()
    test_invalid_status_rejected_by_db_constraint()
    test_ownership_query_excludes_other_users_appointment()
    print("ALL OK")
