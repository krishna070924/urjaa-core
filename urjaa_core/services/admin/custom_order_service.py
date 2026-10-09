from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from urjaa_core.models.custom_order import CustomOrder
from urjaa_core.models.custom_order_event import CustomOrderEvent
from urjaa_core.models.custom_order_status import TERMINAL_STATUS_CODES, CustomOrderStatus
from urjaa_core.models.karigar import Karigar
from urjaa_core.schemas.admin.custom_orders import (
    CustomOrderCreateRequest,
    CustomOrderKarigarAssignRequest,
    CustomOrderStatusUpdateRequest,
    CustomOrderUpdateRequest,
    KarigarCreateRequest,
    KarigarUpdateRequest,
)

ORDER_TAKEN_CODE = "order_taken"


class AdminKarigarService:
    @staticmethod
    def list_karigars(db: Session, *, store_id: UUID, is_active: bool | None = None) -> list[Karigar]:
        query = db.query(Karigar).filter(Karigar.store_id == store_id)
        if is_active is not None:
            query = query.filter(Karigar.is_active == is_active)
        return query.order_by(Karigar.name.asc()).all()

    @staticmethod
    def get_karigar(db: Session, *, store_id: UUID, karigar_id: int) -> Karigar:
        karigar = (
            db.query(Karigar)
            .filter(Karigar.id == karigar_id, Karigar.store_id == store_id)
            .first()
        )
        if karigar is None:
            raise HTTPException(status_code=404, detail="Karigar not found")
        return karigar

    @staticmethod
    def create_karigar(db: Session, *, store_id: UUID, payload: KarigarCreateRequest) -> Karigar:
        karigar = Karigar(
            store_id=store_id,
            name=payload.name,
            phone=payload.phone,
            speciality=payload.speciality,
            is_active=payload.is_active,
        )
        db.add(karigar)
        db.flush()
        db.refresh(karigar)
        return karigar

    @staticmethod
    def update_karigar(db: Session, *, store_id: UUID, karigar_id: int, payload: KarigarUpdateRequest) -> Karigar:
        karigar = AdminKarigarService.get_karigar(db, store_id=store_id, karigar_id=karigar_id)
        fields = payload.model_fields_set
        if "name" in fields:
            karigar.name = payload.name
        if "phone" in fields:
            karigar.phone = payload.phone
        if "speciality" in fields:
            karigar.speciality = payload.speciality
        if "is_active" in fields:
            karigar.is_active = payload.is_active
        db.flush()
        db.refresh(karigar)
        return karigar


def _status_by_code(db: Session, code: str) -> CustomOrderStatus:
    status = db.query(CustomOrderStatus).filter(CustomOrderStatus.code == code).first()
    if status is None:
        raise HTTPException(status_code=422, detail=f"Unknown status code: {code}")
    return status


class AdminCustomOrderService:
    @staticmethod
    def _to_dict(order: CustomOrder, *, include_events: bool = False) -> dict:
        data = {
            "id": order.id,
            "store_id": order.store_id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "taken_at": order.taken_at,
            "taken_by_admin_id": order.taken_by_admin_id,
            "taken_by_email": order.taken_by_admin.email if order.taken_by_admin else None,
            "karigar_id": order.karigar_id,
            "karigar_name": order.karigar.name if order.karigar else None,
            "status_id": order.status_id,
            "status_code": order.status.code,
            "status_label": order.status.label,
            "design_notes": order.design_notes,
            "reference_image_urls": order.reference_image_urls or [],
            "expected_date": order.expected_date,
            "sale_order_id": order.sale_order_id,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }
        if include_events:
            data["events"] = [
                {
                    "id": event.id,
                    "at": event.at,
                    "by_admin_id": event.by_admin_id,
                    "by_admin_email": event.by_admin.email if event.by_admin else None,
                    "kind": event.kind,
                    "from_value": event.from_value,
                    "to_value": event.to_value,
                    "note": event.note,
                }
                for event in order.events
            ]
        return data

    @staticmethod
    def _base_query(db: Session):
        return db.query(CustomOrder).options(
            joinedload(CustomOrder.status),
            joinedload(CustomOrder.karigar),
            joinedload(CustomOrder.taken_by_admin),
        )

    @staticmethod
    def get_order(db: Session, *, store_id: UUID, order_id: int) -> CustomOrder:
        order = (
            AdminCustomOrderService._base_query(db)
            .filter(CustomOrder.id == order_id, CustomOrder.store_id == store_id)
            .first()
        )
        if order is None:
            raise HTTPException(status_code=404, detail="Custom order not found")
        return order

    @staticmethod
    def get_order_response(db: Session, *, store_id: UUID, order_id: int) -> dict:
        order = (
            AdminCustomOrderService._base_query(db)
            .options(joinedload(CustomOrder.events).joinedload(CustomOrderEvent.by_admin))
            .filter(CustomOrder.id == order_id, CustomOrder.store_id == store_id)
            .first()
        )
        if order is None:
            raise HTTPException(status_code=404, detail="Custom order not found")
        return AdminCustomOrderService._to_dict(order, include_events=True)

    @staticmethod
    def list_orders(
        db: Session,
        *,
        store_id: UUID,
        status_code: str | None = None,
        karigar_id: int | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        query = AdminCustomOrderService._base_query(db).filter(CustomOrder.store_id == store_id)

        if status_code:
            query = query.join(CustomOrderStatus, CustomOrder.status_id == CustomOrderStatus.id).filter(
                CustomOrderStatus.code == status_code
            )
        if karigar_id is not None:
            query = query.filter(CustomOrder.karigar_id == karigar_id)
        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(CustomOrder.customer_name.ilike(term), CustomOrder.customer_phone.ilike(term))
            )

        total = query.count()
        rows = (
            query.order_by(CustomOrder.taken_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return [AdminCustomOrderService._to_dict(row) for row in rows], total

    @staticmethod
    def create_order(
        db: Session,
        *,
        store_id: UUID,
        admin_id: int | None,
        payload: CustomOrderCreateRequest,
        sale_order_id: UUID | None = None,
    ) -> dict:
        status = _status_by_code(db, ORDER_TAKEN_CODE)
        order = CustomOrder(
            store_id=store_id,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            taken_by_admin_id=admin_id,
            status_id=status.id,
            # Orders are often logged after the fact; default is now.
            **({"taken_at": payload.taken_at} if payload.taken_at else {}),
            design_notes=payload.design_notes,
            reference_image_urls=payload.reference_image_urls,
            expected_date=payload.expected_date,
            # POS: alteration left at the counter -- the bill it came from.
            sale_order_id=sale_order_id,
        )
        db.add(order)
        db.flush()

        db.add(
            CustomOrderEvent(
                order_id=order.id,
                by_admin_id=admin_id,
                kind="created",
                to_value=status.code,
            )
        )
        db.flush()
        return AdminCustomOrderService.get_order_response(db, store_id=store_id, order_id=order.id)

    @staticmethod
    def update_order(
        db: Session,
        *,
        store_id: UUID,
        order_id: int,
        admin_id: int | None,
        payload: CustomOrderUpdateRequest,
    ) -> dict:
        order = AdminCustomOrderService.get_order(db, store_id=store_id, order_id=order_id)
        fields = payload.model_fields_set
        if not fields:
            raise HTTPException(status_code=400, detail="At least one field must be provided")

        changed: list[str] = []
        if "customer_name" in fields and payload.customer_name != order.customer_name:
            order.customer_name = payload.customer_name
            changed.append("customer_name")
        if "customer_phone" in fields and payload.customer_phone != order.customer_phone:
            order.customer_phone = payload.customer_phone
            changed.append("customer_phone")
        if "design_notes" in fields and payload.design_notes != order.design_notes:
            order.design_notes = payload.design_notes
            changed.append("design_notes")
        if "reference_image_urls" in fields and payload.reference_image_urls != order.reference_image_urls:
            order.reference_image_urls = payload.reference_image_urls
            changed.append("reference_image_urls")
        if "expected_date" in fields and payload.expected_date != order.expected_date:
            order.expected_date = payload.expected_date
            changed.append("expected_date")

        if changed:
            db.add(
                CustomOrderEvent(
                    order_id=order.id,
                    by_admin_id=admin_id,
                    kind="edit",
                    note=f"updated: {', '.join(changed)}",
                )
            )
        db.flush()
        return AdminCustomOrderService.get_order_response(db, store_id=store_id, order_id=order_id)

    @staticmethod
    def set_status(
        db: Session,
        *,
        store_id: UUID,
        order_id: int,
        admin_id: int | None,
        payload: CustomOrderStatusUpdateRequest,
    ) -> dict:
        order = AdminCustomOrderService.get_order(db, store_id=store_id, order_id=order_id)
        new_status = _status_by_code(db, payload.status_code)
        current_code = order.status.code

        if new_status.code == current_code:
            return AdminCustomOrderService.get_order_response(db, store_id=store_id, order_id=order_id)

        # D44: a terminal status (delivered/cancelled) only moves on with an
        # explicit reopen -- the from/to pair on the logged event IS the
        # reopen record, no extra column needed.
        if current_code in TERMINAL_STATUS_CODES and not payload.reopen:
            raise HTTPException(
                status_code=422,
                detail=f"Order is {current_code}; pass reopen=true to move it to another status",
            )

        # Assign the relationship object (not just status_id) so the
        # already-loaded `order.status` attribute on this identity-mapped
        # instance is updated in place -- a bare FK-column write would leave
        # the cached relationship stale for the rest of this session.
        order.status = new_status
        db.add(
            CustomOrderEvent(
                order_id=order.id,
                by_admin_id=admin_id,
                kind="status",
                from_value=current_code,
                to_value=new_status.code,
                note=payload.note,
            )
        )
        db.flush()
        return AdminCustomOrderService.get_order_response(db, store_id=store_id, order_id=order_id)

    @staticmethod
    def assign_karigar(
        db: Session,
        *,
        store_id: UUID,
        order_id: int,
        admin_id: int | None,
        payload: CustomOrderKarigarAssignRequest,
    ) -> dict:
        order = AdminCustomOrderService.get_order(db, store_id=store_id, order_id=order_id)
        from_label = order.karigar.name if order.karigar else None

        if payload.karigar_id is None:
            order.karigar = None  # same staleness reasoning as set_status
            to_label = None
        else:
            karigar = AdminKarigarService.get_karigar(db, store_id=store_id, karigar_id=payload.karigar_id)
            if not karigar.is_active:
                raise HTTPException(status_code=422, detail="Karigar is not active")
            order.karigar = karigar
            to_label = karigar.name

        if from_label != to_label:
            db.add(
                CustomOrderEvent(
                    order_id=order.id,
                    by_admin_id=admin_id,
                    kind="karigar",
                    from_value=from_label,
                    to_value=to_label,
                )
            )
        db.flush()
        return AdminCustomOrderService.get_order_response(db, store_id=store_id, order_id=order_id)
