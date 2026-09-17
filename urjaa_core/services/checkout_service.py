import logging
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from urjaa_core.models.order import Order
from urjaa_core.models.order_item import OrderItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.schemas.checkout import CheckoutCreateRequest
from urjaa_core.services.pricing_service import PricingService, round_money


class CheckoutService:
    logger = logging.getLogger("uvicorn.error")

    @staticmethod
    def _select_product_image_url(product: Product) -> str | None:
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
    def create_order(
        db: Session, payload: CheckoutCreateRequest, store_id: UUID | None, user_id: UUID
    ) -> Order:
        if not payload.items:
            raise HTTPException(status_code=400, detail="At least one checkout item is required")

        normalized_email = payload.email.strip().lower()
        if "@" not in normalized_email:
            raise HTTPException(status_code=400, detail="A valid email is required")

        order_items: list[OrderItem] = []
        total_amount = Decimal("0")

        item_store_ids: list[str] = []

        for item in payload.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product not found: {item.product_id}")

            if product.status != "active":
                raise HTTPException(status_code=400, detail=f"Product is not available: {item.product_id}")

            # H-7 FIX: Use SELECT ... FOR UPDATE to acquire a row-level lock on the variant
            # before checking stock. This matches the pattern used in OrderService.create_order_from_cart
            # and prevents the race condition where two concurrent guest checkouts for the same
            # last-in-stock item both pass the stock check and both create confirmed orders (overselling).
            variant = (
                db.query(ProductVariant)
                .filter(ProductVariant.id == item.variant_id)
                .with_for_update()
                .first()
            )
            if not variant:
                raise HTTPException(status_code=404, detail=f"Variant not found: {item.variant_id}")

            if variant.product_id != item.product_id:
                raise HTTPException(status_code=400, detail="Variant does not belong to product")

            item_store_id = variant.store_id
            if item_store_id is None:
                raise HTTPException(status_code=409, detail="Variant has no store assignment")

            item_store_ids.append(str(item_store_id))

            unit_price = PricingService.calculate_variant_price(variant, db)
            # URJ-066: never create a mispriced order. A missing metal rate now
            # returns None from pricing (instead of raising); checkout must still
            # hard-fail with a clear, transient error rather than proceed.
            if unit_price is None:
                raise HTTPException(
                    status_code=503,
                    detail=f"Pricing is temporarily unavailable for an item in your order "
                           f"({item.variant_id}). Please try again shortly.",
                )
            if unit_price <= 0:
                raise HTTPException(status_code=400, detail="Unable to compute a valid item price")

            # unit_price is already rounded once (calculate_variant_price's boundary);
            # this multiplication is the one place line_total needs its own rounding.
            line_total = round_money(unit_price * item.quantity)
            # Both operands are already 2dp Decimals, so Decimal addition here is
            # exact — no binary-float error to compound, so no further rounding.
            total_amount = total_amount + line_total

            # FIX 2.2 + FIX 3.1: Check stock availability without deducting.
            # Actual stock deduction happens in the payment webhook (_handle_payment_captured)
            # AFTER payment is confirmed, preventing stock loss for unpaid/failed orders.
            available_stock = int(variant.stock_quantity or 0)
            if available_stock < item.quantity:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for variant {item.variant_id}",
                )

            CheckoutService.logger.warning(
                "checkout_create_order stock_check store_id=%s variant_id=%s available=%s requested=%s",
                item_store_id,
                item.variant_id,
                available_stock,
                item.quantity,
            )

            order_items.append(
                OrderItem(
                    store_id=item_store_id,
                    product_id=item.product_id,
                    variant_id=item.variant_id,
                    product_name=product.name,
                    product_image=CheckoutService._select_product_image_url(product),
                    quantity=item.quantity,
                    price=unit_price,
                    unit_price=unit_price,
                    line_total=line_total,
                )
            )

            CheckoutService.logger.warning(
                "checkout_create_order order_item store_id=%s product_id=%s variant_id=%s quantity=%s line_total=%s",
                item_store_id,
                item.product_id,
                item.variant_id,
                item.quantity,
                line_total,
            )

        CheckoutService.logger.warning(
            "checkout_create_order cart_store_ids=%s item_count=%s",
            sorted(set(item_store_ids)),
            len(order_items),
        )

        order_store_id = store_id or order_items[0].store_id

        order = Order(
            store_id=order_store_id,
            user_id=user_id,
            email=normalized_email,
            full_name=payload.full_name,
            phone=payload.phone,
            shipping_address=payload.shipping_address.dict(),
            total_amount=total_amount,
            status="PENDING",
            items=order_items,
        )

        try:
            db.add(order)
            db.commit()
            db.refresh(order)
            return order
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_order(db: Session, order_id: UUID) -> Order | None:
        return db.query(Order).filter(Order.id == order_id).first()
