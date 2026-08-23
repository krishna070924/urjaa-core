import logging
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from urjaa_core.models.address import Address
from urjaa_core.models.cart import Cart
from urjaa_core.models.cart_item import CartItem
from urjaa_core.models.order import Order
from urjaa_core.models.order_item import OrderItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.sale import Sale
from urjaa_core.models.user import User
from urjaa_core.services.pricing_service import PricingService

ORDER_STATUS_VALUES = ("PENDING", "CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED")
ORDER_STATUS_SET = set(ORDER_STATUS_VALUES)
SALE_STATUS_VALUES = ORDER_STATUS_VALUES + ("COMPLETED",)
SALE_STATUS_SET = set(SALE_STATUS_VALUES)

# M-8 FIX: Enforce a valid state machine for order status transitions.
# Without this, any admin with manage_orders permission could move an order from
# DELIVERED back to PENDING, or from CANCELLED back to CONFIRMED, with no
# business logic validation — creating inconsistent order history and potential
# for fraud (e.g., re-activating a cancelled paid order).
#
# The allowed forward-only transitions are:
#   PENDING  -> CONFIRMED | CANCELLED
#   CONFIRMED -> PROCESSING | CANCELLED
#   PROCESSING -> SHIPPED | CANCELLED
#   SHIPPED  -> DELIVERED
#   DELIVERED -> (terminal — no further transitions)
#   CANCELLED -> (terminal — no further transitions)
VALID_ORDER_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING":    ("CONFIRMED", "CANCELLED"),
    "CONFIRMED":  ("PROCESSING", "CANCELLED"),
    "PROCESSING": ("SHIPPED", "CANCELLED"),
    "SHIPPED":    ("DELIVERED",),
    "DELIVERED":  (),
    "CANCELLED":  (),
}

logger = logging.getLogger("uvicorn.error")


class OrderService:
    @staticmethod
    def _normalize_status(status: str | None) -> str | None:
        if status is None:
            return None

        normalized = status.strip().upper()
        if normalized not in ORDER_STATUS_SET:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed values: {', '.join(ORDER_STATUS_VALUES)}",
            )

        return normalized

    @staticmethod
    def _select_product_image_url(item: CartItem) -> str | None:
        product = item.product
        if product is None:
            return None

        images = list(product.images or [])
        if not images:
            return None

        sorted_images = sorted(
            images,
            key=lambda image: (
                0 if bool(image.is_primary) else 1,
                int(image.display_order or 0),
                int(image.id or 0),
            ),
        )
        return sorted_images[0].image_url

    @staticmethod
    def _snapshot_shipping_address(address: Address) -> dict[str, str | None]:
        return {
            "name": address.name,
            "phone": address.phone,
            "line1": address.address_line_1,
            "line2": address.address_line_2,
            "city": address.city,
            "state": address.state,
            "postal_code": address.pincode,
            "country": address.country,
        }

    @staticmethod
    def _ensure_positive_pagination(page: int, limit: int) -> tuple[int, int]:
        normalized_page = page if page > 0 else 1
        normalized_limit = limit if 1 <= limit <= 100 else 20
        return normalized_page, normalized_limit

    @staticmethod
    def _normalize_sale_status(status: str) -> str:
        normalized = status.strip().upper()
        return normalized if normalized in SALE_STATUS_SET else "COMPLETED"

    @staticmethod
    def create_order_from_cart(
        db: Session,
        *,
        current_user: User,
        address_id: UUID,
        store_id: UUID | None = None,
    ) -> Order:
        address = (
            db.query(Address)
            .filter(Address.id == address_id, Address.user_id == current_user.id)
            .first()
        )

        if address is None:
            raise HTTPException(status_code=404, detail="Address not found")

        cart = db.query(Cart).filter(Cart.user_id == current_user.id).first()
        if cart is None:
            raise HTTPException(status_code=400, detail="Cart is empty")

        cart_items = (
            db.query(CartItem)
            .options(
                joinedload(CartItem.product).joinedload(Product.images),
                joinedload(CartItem.variant),
            )
            .filter(CartItem.cart_id == cart.id)
            .all()
        )

        if not cart_items:
            raise HTTPException(status_code=400, detail="Cart is empty")

        variant_ids = [item.variant_id for item in cart_items]
        locked_variants = (
            db.query(ProductVariant)
            .filter(ProductVariant.id.in_(variant_ids))
            .with_for_update()
            .all()
        )
        variants_by_id = {variant.id: variant for variant in locked_variants}

        cart_store_ids = sorted(
            {str(variant.store_id) for variant in locked_variants if variant.store_id is not None}
        )
        logger.warning(
            "create_order_from_cart cart_store_ids=%s user_id=%s cart_item_count=%s",
            cart_store_ids,
            current_user.id,
            len(cart_items),
        )

        total_amount = 0.0
        total_quantity = 0
        total_cost_amount = 0.0
        order_items: list[OrderItem] = []
        rate_cache: dict[int, object] = {}

        for cart_item in cart_items:
            product = cart_item.product
            variant = variants_by_id.get(cart_item.variant_id)

            if product is None or variant is None:
                raise HTTPException(status_code=409, detail="Cart item references unavailable product variant")

            if product.status != "active":
                raise HTTPException(status_code=409, detail=f"Product is not available: {product.name}")

            if variant.product_id != product.id:
                raise HTTPException(status_code=409, detail="Variant does not belong to selected product")

            item_store_id = variant.store_id
            if item_store_id is None:
                raise HTTPException(status_code=409, detail="Variant has no store assignment")

            available_stock = int(variant.stock_quantity or 0)
            requested_quantity = int(cart_item.quantity or 0)
            if requested_quantity <= 0:
                raise HTTPException(status_code=400, detail="Cart contains invalid quantity")

            if available_stock < requested_quantity:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for {product.name}",
                )

            # URJ-066: never create a mispriced order. Pricing returns None on a
            # missing metal rate; order creation must hard-fail cleanly instead of
            # crashing on float(None) or snapshotting a wrong price.
            raw_price = PricingService.calculate_variant_price(variant, db, rate_cache=rate_cache)
            if raw_price is None:
                raise HTTPException(
                    status_code=503,
                    detail=f"Pricing is temporarily unavailable for {product.name}. Please try again shortly.",
                )
            unit_price = round(float(raw_price), 2)
            if unit_price <= 0:
                raise HTTPException(status_code=400, detail=f"Unable to compute price for {product.name}")

            line_total = round(unit_price * requested_quantity, 2)
            total_amount = round(total_amount + line_total, 2)
            total_quantity += requested_quantity

            line_cost_total = round(float(variant.cost_price or 0) * requested_quantity, 2)
            total_cost_amount = round(total_cost_amount + line_cost_total, 2)

            variant.stock_quantity = available_stock - requested_quantity

            logger.warning(
                "create_order_from_cart inventory_deduction store_id=%s variant_id=%s before=%s deduct=%s after=%s",
                item_store_id,
                variant.id,
                available_stock,
                requested_quantity,
                variant.stock_quantity,
            )

            order_items.append(
                OrderItem(
                    store_id=item_store_id,
                    product_id=product.id,
                    variant_id=variant.id,
                    product_name=product.name,
                    product_image=OrderService._select_product_image_url(cart_item),
                    quantity=requested_quantity,
                    price=unit_price,
                    unit_price=unit_price,
                    line_total=line_total,
                )
            )

            logger.warning(
                "create_order_from_cart order_item store_id=%s product_id=%s variant_id=%s quantity=%s line_total=%s",
                item_store_id,
                product.id,
                variant.id,
                requested_quantity,
                line_total,
            )

        representative_store_id = order_items[0].store_id
        order_store_id = store_id or representative_store_id
        unique_item_store_ids = sorted({str(item.store_id) for item in order_items})
        logger.warning(
            "create_order_from_cart resolved_order_store_id=%s provided_store_id=%s unique_item_store_ids=%s",
            order_store_id,
            store_id,
            unique_item_store_ids,
        )

        full_name = (current_user.full_name or "").strip() or (address.name or "").strip() or "Customer"
        email = current_user.email.strip().lower()

        order = Order(
            store_id=order_store_id,
            user_id=current_user.id,
            email=email,
            full_name=full_name,
            phone=(address.phone or current_user.phone),
            shipping_address=OrderService._snapshot_shipping_address(address),
            total_amount=total_amount,
            status="PENDING",
            items=order_items,
        )

        # FIX 3.3: Wrap order + sale creation in a savepoint so both succeed or both roll back atomically.
        sp = db.begin_nested()
        try:
            db.add(order)
            db.flush()

            representative_item = order_items[0]
            sale_store_id = order_store_id or representative_item.store_id
            website_sale = Sale(
                store_id=sale_store_id,
                order_id=order.id,
                product_id=representative_item.product_id,
                variant_id=representative_item.variant_id,
                customer_id=current_user.id,
                quantity=max(total_quantity, 1),
                total_amount=total_amount,
                final_price=total_amount,
                cost_price=total_cost_amount,
                profit=round(total_amount - total_cost_amount, 2),
                source="website",
                status="PENDING",
                date_time=order.created_at,
            )

            logger.warning(
                "create_order_from_cart sale_linked order_id=%s sale_store_id=%s",
                order.id,
                sale_store_id,
            )
            db.add(website_sale)

            for cart_item in cart_items:
                db.delete(cart_item)

            sp.commit()
        except Exception:
            sp.rollback()
            raise

        # FIX 2.1: Cart deletions are flushed here but committed by the calling route handler
        # (orders.py POST /orders calls db.commit() after this function returns).
        # Both the order creation and cart deletion are committed atomically in that outer commit.
        db.flush()
        db.refresh(order)
        return order

    @staticmethod
    def list_user_orders(
        db: Session,
        *,
        user_id: UUID,
        page: int,
        limit: int,
        status: str | None = None,
    ) -> dict:
        normalized_page, normalized_limit = OrderService._ensure_positive_pagination(page, limit)
        status_filter = OrderService._normalize_status(status)

        query = (
            db.query(Order)
            .options(selectinload(Order.items))
            .filter(Order.user_id == user_id)
        )

        if status_filter is not None:
            query = query.filter(Order.status == status_filter)

        total = query.count()
        pages = max(1, ceil(total / normalized_limit)) if total > 0 else 1

        items = (
            query
            .order_by(Order.created_at.desc())
            .offset((normalized_page - 1) * normalized_limit)
            .limit(normalized_limit)
            .all()
        )

        return {
            "items": items,
            "page": normalized_page,
            "limit": normalized_limit,
            "total": total,
            "pages": pages,
        }

    @staticmethod
    def get_user_order(db: Session, *, user_id: UUID, order_id: UUID) -> Order:
        order = (
            db.query(Order)
            .options(selectinload(Order.items))
            .filter(Order.id == order_id, Order.user_id == user_id)
            .first()
        )

        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        return order

    @staticmethod
    def list_admin_orders(
        db: Session,
        *,
        page: int,
        limit: int,
        status: str | None = None,
        customer: str | None = None,
    ) -> dict:
        normalized_page, normalized_limit = OrderService._ensure_positive_pagination(page, limit)
        status_filter = OrderService._normalize_status(status)

        # Global website orders query (no store predicate).
        # We also include legacy rows that were created before sales linkage,
        # where the order exists but no sales row is present yet.
        website_order_filter = or_(Sale.source == "website", Sale.id.is_(None))

        # Effective query shape:
        # SELECT orders.*
        # FROM orders
        # LEFT JOIN sales ON sales.order_id = orders.id
        # WHERE sales.source = 'website' OR sales.id IS NULL
        ids_query = (
            db.query(Order.id, Order.created_at)
            .outerjoin(Sale, Sale.order_id == Order.id)
            .filter(website_order_filter)
            .group_by(Order.id, Order.created_at)
        )

        if status_filter is not None:
            ids_query = ids_query.filter(Order.status == status_filter)

        if customer and customer.strip():
            pattern = f"%{customer.strip()}%"
            ids_query = ids_query.filter(
                or_(
                    Order.full_name.ilike(pattern),
                    Order.email.ilike(pattern),
                )
            )

        total = ids_query.count()
        pages = max(1, ceil(total / normalized_limit)) if total > 0 else 1

        order_ids = [
            order_id
            for (order_id, _created_at) in ids_query
            .order_by(Order.created_at.desc())
            .offset((normalized_page - 1) * normalized_limit)
            .limit(normalized_limit)
            .all()
        ]

        if order_ids:
            items = (
                db.query(Order)
                .options(selectinload(Order.items))
                .filter(Order.id.in_(order_ids))
                .order_by(Order.created_at.desc())
                .all()
            )
        else:
            items = []

        return {
            "items": items,
            "page": normalized_page,
            "limit": normalized_limit,
            "total": total,
            "pages": pages,
        }

    @staticmethod
    def update_admin_order_status(
        db: Session,
        *,
        order_id: UUID,
        status: str,
    ) -> Order:
        normalized_status = OrderService._normalize_status(status)
        if normalized_status is None:
            raise HTTPException(status_code=400, detail="Status is required")

        order = (
            db.query(Order)
            .options(selectinload(Order.items))
            .outerjoin(Sale, Sale.order_id == Order.id)
            .filter(Order.id == order_id)
            .filter(or_(Sale.source == "website", Sale.id.is_(None)))
            .first()
        )

        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        # M-8 FIX: Validate the transition against the state machine before applying.
        current_status = (order.status or "").strip().upper()
        allowed_next = VALID_ORDER_STATUS_TRANSITIONS.get(current_status, ())
        if normalized_status not in allowed_next:
            if current_status == normalized_status:
                raise HTTPException(
                    status_code=400,
                    detail=f"Order is already in status '{normalized_status}'.",
                )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid status transition: cannot move order from "
                    f"'{current_status}' to '{normalized_status}'. "
                    f"Allowed next statuses: {list(allowed_next) or ['none (terminal state)']}"
                ),
            )

        order.status = normalized_status

        # H9 FIX: Restore stock when an admin cancels an order that already had stock
        # deducted. PENDING, CONFIRMED, and PROCESSING orders all deduct stock at
        # creation time (see create_order_from_cart) and can all transition to
        # CANCELLED per VALID_ORDER_STATUS_TRANSITIONS above. Without this, admin
        # cancellation permanently loses stock.
        if normalized_status == "CANCELLED" and current_status in ("PENDING", "CONFIRMED", "PROCESSING"):
            for item in order.items:
                variant = item.variant
                if variant is not None:
                    variant.stock_quantity = (variant.stock_quantity or 0) + item.quantity

        linked_sale = (
            db.query(Sale)
            .filter(Sale.order_id == order.id, Sale.source == "website")
            .first()
        )
        if linked_sale is not None:
            linked_sale.status = OrderService._normalize_sale_status(normalized_status)

        # Schedule post-purchase triggers when order is delivered
        if normalized_status == "DELIVERED":
            try:
                from urjaa_core.services.post_purchase_service import schedule_post_purchase_triggers
                schedule_post_purchase_triggers(order.id, db)
            except Exception:
                logger.exception(
                    "update_admin_order_status: failed to schedule post_purchase_triggers for order %s",
                    order_id,
                )

        db.flush()
        db.refresh(order)
        return order
