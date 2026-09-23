import csv
from contextlib import contextmanager
from datetime import datetime, timezone; UTC = timezone.utc
from io import BytesIO, StringIO
import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from urjaa_core.core.user_auth import (
    USER_SOURCE_STORE,
    USER_SOURCE_VALUES,
    hash_user_password,
    normalize_user_email,
)
from urjaa_core.models.order import Order
from urjaa_core.models.sale import Sale
from urjaa_core.models.store import Store
from urjaa_core.models.user import User
from urjaa_core.repositories.admin.sales_repository import SalesRepository
from urjaa_core.schemas.admin.sales import (
    BulkSaleCreateRequest,
    BulkSaleItemRequest,
    CustomerCreateRequest,
    CustomerUpdateRequest,
    SaleCreateRequest,
)


class SalesService:
    DEFAULT_LOW_STOCK_THRESHOLD = 5
    SOURCE_STORE: Literal["store", "website"] = "store"
    SOURCE_WEBSITE: Literal["store", "website"] = "website"

    @staticmethod
    def _to_customer_response(user: User, store_name: str | None = None) -> dict:
        return {
            "id": user.id,
            "name": user.full_name,
            "store_id": user.last_store_id,
            "store_name": store_name,
            "phone": user.phone,
            "email": user.email,
            "address": user.address,
            "feedback": user.feedback,
            "source": user.source if user.source in USER_SOURCE_VALUES else USER_SOURCE_STORE,
            "is_deleted": not bool(user.is_active),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    @staticmethod
    def _resolve_customer_store_tag(
        db: Session,
        *,
        payload_store_id: UUID | None,
        active_store_id: UUID | None,
    ) -> UUID | None:
        resolved_store_id = payload_store_id or active_store_id
        if resolved_store_id is None:
            return None

        store = db.query(Store.id).filter(Store.id == resolved_store_id).first()
        if store is None:
            raise HTTPException(status_code=400, detail="Invalid store tag")

        return resolved_store_id

    @staticmethod
    def _generate_store_customer_email(db: Session) -> str:
        while True:
            candidate = f"store-customer-{uuid4().hex}@store.local"
            exists = db.query(User.id).filter(func.lower(User.email) == candidate).first()
            if exists is None:
                return candidate

    @staticmethod
    @contextmanager
    def _transaction_scope(db: Session):
        # Use a real transaction boundary for each sales operation.
        # If the caller already opened one (e.g., sandbox harness), use a savepoint.
        if db.in_transaction():
            with db.begin_nested():
                yield
            return

        with db.begin():
            yield

    @staticmethod
    def _build_invoice_number(sale_id: UUID, date_time: datetime) -> str:
        return f"INV-{date_time.strftime('%Y%m%d')}-{str(sale_id).split('-')[0].upper()}"

    @staticmethod
    def _generate_order_invoice_number(db: Session, store_id: UUID, date_time: datetime) -> str:
        """Atomic, gapless-under-concurrency sequence per (store, month).

        Postgres UPSERT (INSERT ... ON CONFLICT DO UPDATE) takes a row-level
        lock for the duration of the statement, so concurrent callers for the
        same (store_id, period) serialize on it instead of racing a
        read-then-write. No app-level locking needed.
        """
        period = date_time.strftime("%Y%m")
        seq = db.execute(
            text(
                """
                INSERT INTO invoice_sequences (store_id, period, seq)
                VALUES (:store_id, :period, 1)
                ON CONFLICT (store_id, period)
                DO UPDATE SET seq = invoice_sequences.seq + 1
                RETURNING seq
                """
            ),
            {"store_id": store_id, "period": period},
        ).scalar_one()
        store_code = str(store_id).replace("-", "")[:8].upper()
        return f"INV-{store_code}-{period}-{seq}"

    @staticmethod
    def _to_sale_response(sale: Sale) -> dict:
        is_website_order = sale.source == SalesService.SOURCE_WEBSITE and sale.order_id is not None
        variant_stock = sale.variant.stock_quantity if sale.variant and not is_website_order else 0
        total_cost_price = float(sale.cost_price or 0)
        total_profit = float(sale.profit or (float(sale.final_price or 0) - total_cost_price))
        total_amount = float(sale.total_amount or sale.final_price or 0)
        sale_status = (sale.status or "COMPLETED").upper()
        if sale_status not in {"PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED", "COMPLETED"}:
            sale_status = "COMPLETED"

        if is_website_order:
            short_order_id = str(sale.order_id).split("-")[0]
            product_name = f"Website Order {short_order_id}"
            sku_code = None
        else:
            product_name = sale.product.name if sale.product else "Unknown Product"
            sku_code = sale.variant.sku_code if sale.variant else None

        return {
            "id": sale.id,
            "order_id": sale.order_id,
            "product_id": sale.product_id,
            "product_name": product_name,
            "variant_id": sale.variant_id,
            "sku_code": sku_code,
            "customer_id": sale.customer_id,
            "customer_name": sale.customer.full_name if sale.customer else None,
            "quantity": sale.quantity,
            "total_amount": total_amount,
            "final_price": float(sale.final_price),
            "cost_price": total_cost_price,
            "profit": total_profit,
            "source": sale.source,
            "status": sale_status,
            "date_time": sale.date_time,
            "stock_after": variant_stock,
            "is_low_stock": 0 < variant_stock <= SalesService.DEFAULT_LOW_STOCK_THRESHOLD,
            "is_out_of_stock": variant_stock <= 0,
        }

    @staticmethod
    def _get_metal_rate(db: Session, metal_type: str) -> float:
        metal_rate = SalesRepository.get_latest_rate_by_metal_type(db, metal_type)
        if metal_rate is None:
            raise HTTPException(status_code=400, detail="No valid metal rate configured")
        return metal_rate

    @staticmethod
    def _compute_cost_and_profit(
        db: Session,
        variant,
        quantity: int,
        final_price: float,
        item_weight: float | None = None,
    ) -> tuple[float, float]:
        # Use request weight when explicitly provided; otherwise fallback to variant weight.
        resolved_weight = item_weight if item_weight is not None else variant.weight
        weight = float(resolved_weight if resolved_weight is not None else (variant.metal_weight_grams or 0))
        if weight <= 0:
            raise HTTPException(status_code=400, detail="Variant weight must be greater than 0")

        making_charges = float(variant.making_charges or 0)
        if making_charges < 0:
            raise HTTPException(status_code=400, detail="Variant making charges must be greater than or equal to 0")

        metal_type = (variant.metal_type or "").strip()
        if not metal_type and variant.base_metal is not None:
            metal_type = variant.base_metal.name
        if not metal_type:
            raise HTTPException(status_code=400, detail="Variant metal type is required")

        metal_rate = SalesService._get_metal_rate(db, metal_type)
        unit_cost_price = (weight * metal_rate) + making_charges
        total_cost_price = round(unit_cost_price * quantity, 2)
        total_profit = round(float(final_price) - total_cost_price, 2)
        return total_cost_price, total_profit

    @staticmethod
    def _validate_sale_item(
        db: Session,
        store_id: UUID,
        item: SaleCreateRequest | BulkSaleItemRequest,
    ) -> tuple:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be at least 1")
        if item.final_price <= 0:
            raise HTTPException(status_code=400, detail="Final price must be greater than 0")

        product = SalesRepository.get_product_by_id(db, item.product_id, store_id=store_id)
        if not product:
            raise HTTPException(status_code=404, detail="Selected product was not found")

        variant = SalesRepository.get_variant_by_id_for_update(db, item.variant_id, store_id=store_id)
        if not variant:
            raise HTTPException(status_code=404, detail="Selected variant was not found")
        if variant.product_id != item.product_id:
            raise HTTPException(status_code=400, detail="Selected variant does not belong to selected product")

        if variant.stock_quantity < 0:
            raise HTTPException(
                status_code=409,
                detail="Inventory data is inconsistent for this variant. Please update stock before creating a sale.",
            )

        if variant.stock_quantity <= 0:
            raise HTTPException(status_code=409, detail="This variant is out of stock")
        if item.quantity > variant.stock_quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Only {variant.stock_quantity} unit(s) are currently available for this variant",
            )

        return product, variant

    @staticmethod
    def _build_sale_record(
        store_id: UUID,
        item: SaleCreateRequest | BulkSaleItemRequest,
        total_cost_price: float,
        total_profit: float,
        customer_id: UUID | None,
        source: Literal["store", "website"],
        date_time: datetime,
        order_id: UUID | None = None,
        sale_status: str = "COMPLETED",
    ) -> Sale:
        if total_cost_price is None or total_profit is None:
            raise HTTPException(status_code=500, detail="Failed to compute sale profitability fields")

        return Sale(
            store_id=store_id,
            order_id=order_id,
            product_id=item.product_id,
            variant_id=item.variant_id,
            customer_id=customer_id,
            quantity=item.quantity,
            total_amount=item.final_price,
            final_price=item.final_price,
            cost_price=total_cost_price,
            profit=total_profit,
            source=source,
            status=sale_status,
            date_time=date_time,
        )

    @staticmethod
    def get_summary(db: Session, store_id: UUID) -> dict:
        variants = SalesRepository.get_variants_for_catalog_estimation(db, store_id=store_id)
        latest_rate_map = SalesRepository.get_latest_metal_rate_map(db)

        estimated_catalog_value = 0.0
        for variant in variants:
            if variant.stock_quantity <= 0:
                continue

            if variant.price_override is not None:
                unit_price = float(variant.price_override)
            else:
                rate_per_gram = latest_rate_map.get(int(variant.base_metal_id or 0), 0.0)
                metal_weight = float(variant.metal_weight_grams or 0.0)
                stone_cost = float(variant.stone_cost or 0.0)
                making_charges = float(variant.making_charges or 0.0)
                unit_price = (metal_weight * rate_per_gram) + stone_cost + making_charges

            estimated_catalog_value += unit_price * float(variant.stock_quantity)

        return {
            "active_products": SalesRepository.count_products_by_status(db, "active", store_id=store_id),
            "draft_products": SalesRepository.count_products_by_status(db, "draft", store_id=store_id),
            "archived_products": SalesRepository.count_products_by_status(db, "archived", store_id=store_id),
            "featured_products": SalesRepository.count_featured_products(db, store_id=store_id),
            "total_variants": SalesRepository.count_variants(db, store_id=store_id),
            "in_stock_variants": SalesRepository.count_in_stock_variants(db, store_id=store_id),
            "out_of_stock_variants": SalesRepository.count_out_of_stock_variants(db, store_id=store_id),
            "estimated_catalog_value": round(estimated_catalog_value, 2),
            "currency": "INR",
            "note": "Sales summary is currently derived from catalog and inventory signals. Integrate order data for transactional GMV/revenue metrics.",
        }

    @staticmethod
    def list_customers(db: Session, store_id: UUID | None, page: int, limit: int) -> dict:
        return SalesService.list_customers_with_options(
            db,
            store_id=store_id,
            page=page,
            limit=limit,
            include_deleted=False,
        )

    @staticmethod
    def list_customers_with_options(
        db: Session,
        store_id: UUID | None,
        page: int,
        limit: int,
        include_deleted: bool = False,
    ) -> dict:
        total = SalesRepository.count_customers(db, include_deleted=include_deleted)
        pages = max(1, (total + limit - 1) // limit)
        items = SalesRepository.list_customers(
            db,
            page=page,
            limit=limit,
            include_deleted=include_deleted,
        )

        tagged_store_ids = sorted({item.last_store_id for item in items if item.last_store_id is not None})
        store_name_by_id: dict[UUID, str] = {}
        if tagged_store_ids:
            store_rows = db.query(Store.id, Store.name).filter(Store.id.in_(tagged_store_ids)).all()
            store_name_by_id = {store_id_row: store_name for store_id_row, store_name in store_rows}

        return {
            "items": [
                SalesService._to_customer_response(item, store_name_by_id.get(item.last_store_id))
                for item in items
            ],
            "page": page,
            "limit": limit,
            "total": total,
            "pages": pages,
        }

    @staticmethod
    def create_customer(db: Session, store_id: UUID | None, payload: CustomerCreateRequest) -> dict:
        normalized_name = payload.name.strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="Customer name is required")

        resolved_store_tag = SalesService._resolve_customer_store_tag(
            db,
            payload_store_id=payload.store_id,
            active_store_id=store_id,
        )

        normalized_email: str
        if payload.email and payload.email.strip():
            normalized_email = normalize_user_email(payload.email)
            existing = (
                db.query(User)
                .filter(func.lower(User.email) == normalized_email)
                .first()
            )
            if existing is not None:
                raise HTTPException(status_code=409, detail="Customer with this email already exists")
        else:
            normalized_email = SalesService._generate_store_customer_email(db)

        customer = User(
            email=normalized_email,
            password_hash=hash_user_password(secrets.token_urlsafe(48)),
            full_name=normalized_name,
            phone=payload.phone.strip() if payload.phone else None,
            last_store_id=resolved_store_tag,
            source=USER_SOURCE_STORE,
            address=payload.address.strip() if payload.address else None,
            feedback=payload.feedback.strip() if payload.feedback else None,
            provider="local",
            provider_id=None,
            is_active=True,
        )
        SalesRepository.create_customer(db, customer)
        db.commit()

        tagged_store_name = None
        if customer.last_store_id is not None:
            tagged_store_name = db.query(Store.name).filter(Store.id == customer.last_store_id).scalar()

        return SalesService._to_customer_response(customer, tagged_store_name)

    @staticmethod
    def update_customer(db: Session, store_id: UUID | None, customer_id: UUID, payload: CustomerUpdateRequest) -> dict:
        customer = SalesRepository.get_customer_by_id(db, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        updates = payload.dict(exclude_unset=True)
        if "name" in updates and updates["name"] is not None:
            normalized_name = updates["name"].strip()
            if not normalized_name:
                raise HTTPException(status_code=400, detail="Customer name is required")
            customer.full_name = normalized_name

        if "phone" in updates:
            customer.phone = updates["phone"].strip() if updates["phone"] else None

        if "email" in updates:
            if updates["email"] and updates["email"].strip():
                normalized_email = normalize_user_email(updates["email"])
                existing = (
                    db.query(User)
                    .filter(func.lower(User.email) == normalized_email, User.id != customer.id)
                    .first()
                )
                if existing is not None:
                    raise HTTPException(status_code=409, detail="Customer with this email already exists")
                customer.email = normalized_email

        if "address" in updates:
            customer.address = updates["address"].strip() if updates["address"] else None

        if "feedback" in updates:
            customer.feedback = updates["feedback"].strip() if updates["feedback"] else None

        resolved_store_tag = SalesService._resolve_customer_store_tag(
            db,
            payload_store_id=updates.get("store_id") if "store_id" in updates else None,
            active_store_id=store_id,
        )
        if resolved_store_tag is not None:
            customer.last_store_id = resolved_store_tag

        if customer.source not in USER_SOURCE_VALUES:
            customer.source = USER_SOURCE_STORE

        SalesRepository.update_customer(db, customer)
        db.commit()

        tagged_store_name = None
        if customer.last_store_id is not None:
            tagged_store_name = db.query(Store.name).filter(Store.id == customer.last_store_id).scalar()

        return SalesService._to_customer_response(customer, tagged_store_name)

    @staticmethod
    def archive_customer(db: Session, store_id: UUID | None, customer_id: UUID) -> dict:
        customer = SalesRepository.get_customer_by_id_any_state(db, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Safety check: we allow archive even with sales, preserving historical integrity.
        _sales_count = SalesRepository.count_sales_by_customer(db, customer_id=customer_id)

        customer.is_active = False
        SalesRepository.update_customer(db, customer)
        db.commit()
        return {"message": "Customer archived successfully"}

    @staticmethod
    def create_sale(
        db: Session,
        store_id: UUID,
        payload: SaleCreateRequest,
        source: Literal["store", "website"] = SOURCE_STORE,
    ) -> dict:
        with SalesService._transaction_scope(db):
            product, variant = SalesService._validate_sale_item(db, store_id=store_id, item=payload)

            customer = None
            if payload.customer_id is not None:
                customer = SalesRepository.get_customer_by_id(db, payload.customer_id)
                if not customer:
                    raise HTTPException(status_code=404, detail="Selected customer was not found")

            updated_stock = variant.stock_quantity - payload.quantity
            if updated_stock < 0:
                raise HTTPException(status_code=409, detail="Sale quantity exceeds available stock")
            variant.stock_quantity = updated_stock

            total_cost_price, total_profit = SalesService._compute_cost_and_profit(
                db=db,
                variant=variant,
                quantity=payload.quantity,
                final_price=payload.final_price,
                item_weight=payload.weight,
            )

            sale = SalesService._build_sale_record(
                store_id=store_id,
                item=payload,
                total_cost_price=total_cost_price,
                total_profit=total_profit,
                customer_id=payload.customer_id,
                source=source,
                date_time=payload.date_time or datetime.now(UTC),
            )

            SalesRepository.create_sale(db, sale)

            response = {
                "id": sale.id,
                "order_id": sale.order_id,
                "product_id": sale.product_id,
                "product_name": product.name,
                "variant_id": sale.variant_id,
                "sku_code": variant.sku_code,
                "customer_id": sale.customer_id,
                "customer_name": customer.full_name if customer else None,
                "quantity": sale.quantity,
                "total_amount": float(sale.total_amount),
                "final_price": float(sale.final_price),
                "cost_price": total_cost_price,
                "profit": total_profit,
                "source": sale.source,
                "status": (sale.status or "COMPLETED").upper(),
                "date_time": sale.date_time,
                "stock_after": variant.stock_quantity,
                "is_low_stock": 0 < variant.stock_quantity <= SalesService.DEFAULT_LOW_STOCK_THRESHOLD,
                "is_out_of_stock": variant.stock_quantity <= 0,
            }
        response["invoice_number"] = SalesService._build_invoice_number(sale.id, sale.date_time)
        return response

    @staticmethod
    def create_bulk_sale(
        db: Session,
        store_id: UUID,
        payload: BulkSaleCreateRequest,
        source: Literal["store", "website"] = SOURCE_STORE,
    ) -> dict:
        created_sales: list[Sale] = []
        total_amount = 0.0
        total_cost_price = 0.0
        total_profit = 0.0
        sale_time = payload.date_time or datetime.now(UTC)

        order_id: UUID | None = None

        with SalesService._transaction_scope(db):
            customer = None
            if payload.customer_id is not None:
                customer = SalesRepository.get_customer_by_id(db, payload.customer_id)
                if not customer:
                    raise HTTPException(status_code=404, detail="Selected customer was not found")

            line_items: list[tuple[BulkSaleItemRequest, float, float]] = []
            for item in payload.items:
                _, variant = SalesService._validate_sale_item(db, store_id=store_id, item=item)

                updated_stock = variant.stock_quantity - item.quantity
                if updated_stock < 0:
                    raise HTTPException(status_code=409, detail="Sale quantity exceeds available stock")
                variant.stock_quantity = updated_stock

                line_cost_price, line_profit = SalesService._compute_cost_and_profit(
                    db=db,
                    variant=variant,
                    quantity=item.quantity,
                    final_price=item.final_price,
                    item_weight=item.weight,
                )
                line_items.append((item, line_cost_price, line_profit))
                total_amount += float(item.final_price)
                total_cost_price += line_cost_price
                total_profit += line_profit

            order = Order(
                store_id=store_id,
                user_id=None,
                email=None,
                full_name=None,
                total_amount=round(total_amount, 2),
                status="COMPLETED",
                source=source,
                invoice_number=SalesService._generate_order_invoice_number(db, store_id, sale_time),
            )
            db.add(order)
            db.flush()
            order_id = order.id

            for item, line_cost_price, line_profit in line_items:
                sale = SalesService._build_sale_record(
                    store_id=store_id,
                    item=item,
                    total_cost_price=line_cost_price,
                    total_profit=line_profit,
                    customer_id=payload.customer_id,
                    source=source,
                    date_time=sale_time,
                    order_id=order_id,
                )
                SalesRepository.create_sale(db, sale)
                created_sales.append(sale)

        return {
            "created_sale_ids": [sale.id for sale in created_sales],
            "order_id": order_id,
            "total_amount": round(total_amount, 2),
            "total_cost_price": round(total_cost_price, 2),
            "total_profit": round(total_profit, 2),
        }

    @staticmethod
    def get_sales_history(
        db: Session,
        store_id: UUID,
        page: int,
        limit: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> dict:
        if start_date and end_date and start_date > end_date:
            raise HTTPException(status_code=400, detail="Start date must be earlier than or equal to end date")

        total = SalesRepository.count_sales(
            db,
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
        )

        sales = SalesRepository.list_sales(
            db,
            store_id=store_id,
            page=page,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
        )

        pages = max(1, (total + limit - 1) // limit)
        return {
            "items": [SalesService._to_sale_response(sale) for sale in sales],
            "page": page,
            "limit": limit,
            "total": total,
            "pages": pages,
        }

    @staticmethod
    def export_sales_csv(
        db: Session,
        store_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        customer_id: UUID | None = None,
    ) -> tuple[str, bytes]:
        sales = SalesRepository.list_sales_for_export(
            db,
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            customer_id=customer_id,
        )
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "sale_id",
                "invoice_number",
                "date_time",
                "product_name",
                "sku_code",
                "customer_name",
                "source",
                "quantity",
                "order_id",
                "final_price",
                "total_amount",
                "cost_price",
                "profit",
                "status",
                "stock_after",
            ]
        )
        for sale in sales:
            sale_response = SalesService._to_sale_response(sale)
            writer.writerow(
                [
                    str(sale.id),
                    SalesService._build_invoice_number(sale.id, sale.date_time),
                    sale.date_time.isoformat(),
                    sale_response["product_name"],
                    sale_response["sku_code"] or "",
                    sale_response["customer_name"] or "Walk-in",
                    sale_response["source"],
                    sale.quantity,
                    str(sale_response["order_id"]) if sale_response["order_id"] else "",
                    sale_response["final_price"],
                    sale_response["total_amount"],
                    sale_response["cost_price"],
                    sale_response["profit"],
                    sale_response["status"],
                    sale_response["stock_after"],
                ]
            )
        data = output.getvalue().encode("utf-8")
        file_name = f"sales_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"
        return file_name, data

    @staticmethod
    def build_invoice_pdf(db: Session, store_id: UUID, sale_id: UUID) -> tuple[str, bytes]:
        sale = SalesRepository.get_sale_by_id(db, sale_id, store_id=store_id)
        if not sale:
            raise HTTPException(status_code=404, detail="Sale record not found")

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Invoice generation is currently unavailable. Please contact support.",
            )

        invoice_number = SalesService._build_invoice_number(sale.id, sale.date_time)
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        y = height - 40
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(40, y, "Urjaa Ornaments")
        y -= 24
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, y, f"Invoice Number: {invoice_number}")
        y -= 16
        pdf.drawString(40, y, f"Invoice Date: {sale.date_time.strftime('%d %b %Y %H:%M')}")

        y -= 30
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, y, "Customer")
        y -= 18
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, y, f"Name: {sale.customer.full_name if sale.customer else 'Walk-in Customer'}")
        y -= 16
        pdf.drawString(40, y, f"Phone: {(sale.customer.phone if sale.customer else '') or '-'}")

        y -= 28
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, y, "Sale Item")
        y -= 18
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, y, f"Product: {sale.product.name if sale.product else 'Unknown Product'}")
        y -= 16
        pdf.drawString(40, y, f"SKU: {(sale.variant.sku_code if sale.variant else None) or '-'}")
        y -= 16
        pdf.drawString(40, y, f"Quantity: {sale.quantity}")

        y -= 28
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, y, "Pricing")
        y -= 18
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, y, f"Total Amount: INR {float(sale.total_amount or sale.final_price):,.2f}")

        pdf.showPage()
        pdf.save()

        pdf_bytes = buffer.getvalue()
        file_name = f"invoice_{invoice_number}.pdf"
        return file_name, pdf_bytes

    @staticmethod
    def get_stock_overview(db: Session, store_id: UUID, low_stock_threshold: int = DEFAULT_LOW_STOCK_THRESHOLD) -> dict:
        low_stock_rows = SalesRepository.get_low_stock_variants(
            db,
            threshold=low_stock_threshold,
            store_id=store_id,
            limit=20,
        )
        out_of_stock_rows = SalesRepository.get_out_of_stock_variants(db, store_id=store_id, limit=20)

        low_stock_items = [
            {
                "product_id": product.id,
                "product_name": product.name,
                "variant_id": variant.id,
                "sku_code": variant.sku_code,
                "stock_quantity": variant.stock_quantity,
            }
            for variant, product in low_stock_rows
        ]

        out_of_stock_items = [
            {
                "product_id": product.id,
                "product_name": product.name,
                "variant_id": variant.id,
                "sku_code": variant.sku_code,
                "stock_quantity": variant.stock_quantity,
            }
            for variant, product in out_of_stock_rows
        ]

        return {
            "low_stock_threshold": low_stock_threshold,
            "low_stock_count": len(low_stock_items),
            "out_of_stock_count": len(out_of_stock_items),
            "low_stock_items": low_stock_items,
            "out_of_stock_items": out_of_stock_items,
        }
