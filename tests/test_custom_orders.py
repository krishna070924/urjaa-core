"""O-04/D44 self-check against the live dev database, as the admin app role.
Savepoint-joined Session, everything rolled back at the end -- same pattern
as tests/test_sku_autogeneration.py.

Covers: create (status order_taken, taken_by admin, "created" event),
assigning an active karigar, rejecting an inactive one, a logged status
move, a rejected bad phone number, and the reopen rule on terminal statuses.

Run: .venv/bin/python tests/test_custom_orders.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import AdminUser, Store
from urjaa_core.schemas.admin.custom_orders import (
    CustomOrderCreateRequest,
    CustomOrderKarigarAssignRequest,
    CustomOrderStatusUpdateRequest,
    KarigarCreateRequest,
)
from urjaa_core.services.admin.custom_order_service import AdminCustomOrderService, AdminKarigarService


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))
        store = db.query(Store).first()
        admin = db.query(AdminUser).first()
        assert store and admin, "dev DB needs at least one store and admin user"

        active_karigar = AdminKarigarService.create_karigar(
            db, store_id=store.id, payload=KarigarCreateRequest(name="Ramesh", phone="9876543210")
        )
        inactive_karigar = AdminKarigarService.create_karigar(
            db,
            store_id=store.id,
            payload=KarigarCreateRequest(name="Suresh", phone="9876500000", is_active=False),
        )
        db.flush()

        # 1. create -> order_taken, taken_by = admin, "created" event logged.
        order = AdminCustomOrderService.create_order(
            db,
            store_id=store.id,
            admin_id=admin.id,
            payload=CustomOrderCreateRequest(customer_name="Priya Shah", customer_phone="+91 98765 11111"),
        )
        assert order["status_code"] == "order_taken"
        assert order["taken_by_admin_id"] == admin.id
        assert order["customer_phone"] == "9876511111"
        assert len(order["events"]) == 1 and order["events"][0]["kind"] == "created"
        print("create -> order_taken, taken_by set, created event   OK")

        # 2. assign an active karigar -> succeeds, "karigar" event logged.
        order = AdminCustomOrderService.assign_karigar(
            db,
            store_id=store.id,
            order_id=order["id"],
            admin_id=admin.id,
            payload=CustomOrderKarigarAssignRequest(karigar_id=active_karigar.id),
        )
        assert order["karigar_id"] == active_karigar.id
        karigar_events = [e for e in order["events"] if e["kind"] == "karigar"]
        assert len(karigar_events) == 1 and karigar_events[0]["to_value"] == "Ramesh"
        print("assign active karigar -> logged                      OK")

        # 3. assigning an inactive karigar is rejected.
        try:
            AdminCustomOrderService.assign_karigar(
                db,
                store_id=store.id,
                order_id=order["id"],
                admin_id=admin.id,
                payload=CustomOrderKarigarAssignRequest(karigar_id=inactive_karigar.id),
            )
            raise AssertionError("inactive karigar accepted")
        except HTTPException as exc:
            assert exc.status_code == 422
        print("inactive karigar -> rejected                         OK")

        # 4. status move is logged with from/to.
        order = AdminCustomOrderService.set_status(
            db,
            store_id=store.id,
            order_id=order["id"],
            admin_id=admin.id,
            payload=CustomOrderStatusUpdateRequest(status_code="design_finalised"),
        )
        assert order["status_code"] == "design_finalised"
        status_events = [e for e in order["events"] if e["kind"] == "status"]
        assert len(status_events) == 1
        assert status_events[0]["from_value"] == "order_taken" and status_events[0]["to_value"] == "design_finalised"
        print("status move -> logged from/to                        OK")

        # 5. a bad phone number is rejected at the schema layer.
        try:
            CustomOrderCreateRequest(customer_name="Bad Phone", customer_phone="12345")
            raise AssertionError("bad phone accepted")
        except ValidationError:
            pass
        print("bad phone -> rejected                                 OK")

        from urjaa_core.schemas.admin.custom_orders import CustomOrderUpdateRequest, KarigarUpdateRequest
        for bad in ({"customer_name": None}, {"customer_phone": None}, {"reference_image_urls": None}):
            try:
                CustomOrderUpdateRequest(**bad)
                raise AssertionError(f"explicit null accepted: {bad}")
            except ValidationError:
                pass
        try:
            KarigarUpdateRequest(name=None)
            raise AssertionError("karigar null name accepted")
        except ValidationError:
            pass
        assert CustomOrderUpdateRequest(design_notes=None).design_notes is None  # clearing notes is fine
        print("explicit null on required field -> 422               OK")

        # 6. reopen rule: delivered/cancelled need reopen=true to move further.
        order = AdminCustomOrderService.set_status(
            db,
            store_id=store.id,
            order_id=order["id"],
            admin_id=admin.id,
            payload=CustomOrderStatusUpdateRequest(status_code="delivered"),
        )
        assert order["status_code"] == "delivered"

        try:
            AdminCustomOrderService.set_status(
                db,
                store_id=store.id,
                order_id=order["id"],
                admin_id=admin.id,
                payload=CustomOrderStatusUpdateRequest(status_code="with_karigar"),
            )
            raise AssertionError("moved out of delivered without reopen")
        except HTTPException as exc:
            assert exc.status_code == 422
        print("terminal status without reopen -> rejected            OK")

        order = AdminCustomOrderService.set_status(
            db,
            store_id=store.id,
            order_id=order["id"],
            admin_id=admin.id,
            payload=CustomOrderStatusUpdateRequest(status_code="with_karigar", reopen=True),
        )
        assert order["status_code"] == "with_karigar"
        reopen_events = [e for e in order["events"] if e["kind"] == "status" and e["from_value"] == "delivered"]
        assert len(reopen_events) == 1 and reopen_events[0]["to_value"] == "with_karigar"
        print("reopen=true -> move allowed and logged                OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
