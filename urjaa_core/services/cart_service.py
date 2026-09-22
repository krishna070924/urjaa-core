from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from urjaa_core.models.cart import Cart
from urjaa_core.models.cart_item import CartItem
from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.variant_attribute import VariantAttribute
from urjaa_core.schemas.cart import CartItemResponse, CartResponse
from urjaa_core.services.pricing_service import PricingService
from urjaa_core.utils.currency import format_inr


class CartService:
    @staticmethod
    def _get_or_create_user_cart(db: Session, *, user_id: UUID) -> Cart:
        cart = db.query(Cart).filter(Cart.user_id == user_id).first()
        if cart is not None:
            return cart

        cart = Cart(user_id=user_id)
        db.add(cart)
        db.flush()
        return cart

    @staticmethod
    def _validate_product_variant(db: Session, *, product_id: UUID, variant_id: UUID) -> tuple[Product, ProductVariant]:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        if product.status != "active":
            raise HTTPException(status_code=400, detail="Product is not available")

        variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id).first()
        if variant is None:
            raise HTTPException(status_code=404, detail="Variant not found")

        if variant.product_id != product.id:
            raise HTTPException(status_code=400, detail="Variant does not belong to product")

        return product, variant

    @staticmethod
    def _ensure_stock(variant: ProductVariant, requested_quantity: int) -> None:
        available_stock = int(variant.stock_quantity or 0)

        if available_stock <= 0:
            raise HTTPException(status_code=409, detail="Variant is out of stock")

        if requested_quantity > available_stock:
            raise HTTPException(status_code=409, detail="Requested quantity exceeds available stock")

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
    def _build_cart_response(db: Session, cart: Cart) -> CartResponse:
        cart_items = (
            db.query(CartItem)
            .options(
                joinedload(CartItem.product).joinedload(Product.images),
                joinedload(CartItem.variant)
                .joinedload(ProductVariant.attribute_values)
                .joinedload(VariantAttribute.attribute_value),
            )
            .filter(CartItem.cart_id == cart.id)
            .all()
        )

        response_items: list[CartItemResponse] = []
        subtotal = 0.0
        has_unpriceable_items = False
        rate_cache: dict = {}

        for item in cart_items:
            # URJ-066: a missing metal rate must not 503 the whole cart. The line is
            # flagged unpriceable (null prices, is_priced=False) and left out of the
            # subtotal; the storefront blocks checkout for it.
            raw_price = PricingService.calculate_variant_price(item.variant, db, rate_cache=rate_cache)

            if raw_price is None:
                has_unpriceable_items = True
                unit_price = None
                line_total = None
            else:
                unit_price = round(float(raw_price), 2)
                line_total = round(unit_price * int(item.quantity), 2)
                subtotal = round(subtotal + line_total, 2)

            response_items.append(
                CartItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    variant_id=item.variant_id,
                    quantity=int(item.quantity),
                    product_name=item.product.name,
                    product_slug=item.product.slug,
                    variant_size=item.variant.attribute_label,
                    image_url=CartService._select_product_image_url(item.product),
                    unit_price=unit_price,
                    line_total=line_total,
                    is_priced=raw_price is not None,
                )
            )

        item_count = sum(entry.quantity for entry in response_items)

        return CartResponse(
            id=cart.id,
            user_id=cart.user_id,
            created_at=cart.created_at,
            items=response_items,
            item_count=item_count,
            subtotal=round(subtotal, 2),
            total=round(subtotal, 2),
            formatted_subtotal=format_inr(subtotal),
            formatted_total=format_inr(subtotal),
            has_unpriceable_items=has_unpriceable_items,
        )

    @staticmethod
    def get_cart(db: Session, *, user_id: UUID) -> CartResponse:
        cart = CartService._get_or_create_user_cart(db, user_id=user_id)
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def add_item(
        db: Session,
        *,
        user_id: UUID,
        product_id: UUID,
        variant_id: UUID,
        quantity: int,
    ) -> CartResponse:
        cart = CartService._get_or_create_user_cart(db, user_id=user_id)
        _, variant = CartService._validate_product_variant(db, product_id=product_id, variant_id=variant_id)

        existing_item = (
            db.query(CartItem)
            .filter(
                CartItem.cart_id == cart.id,
                CartItem.product_id == product_id,
                CartItem.variant_id == variant_id,
            )
            .first()
        )

        if existing_item is not None:
            next_quantity = int(existing_item.quantity) + int(quantity)
            CartService._ensure_stock(variant, next_quantity)
            existing_item.quantity = next_quantity
        else:
            CartService._ensure_stock(variant, int(quantity))
            db.add(
                CartItem(
                    cart_id=cart.id,
                    product_id=product_id,
                    variant_id=variant_id,
                    quantity=int(quantity),
                )
            )

        db.flush()
        return CartService._build_cart_response(db, cart)

    @staticmethod
    def update_item_quantity(db: Session, *, user_id: UUID, item_id: UUID, quantity: int) -> CartResponse:
        cart_item = (
            db.query(CartItem)
            .join(Cart, CartItem.cart_id == Cart.id)
            .options(joinedload(CartItem.variant))
            .filter(CartItem.id == item_id, Cart.user_id == user_id)
            .first()
        )

        if cart_item is None:
            raise HTTPException(status_code=404, detail="Cart item not found")

        CartService._ensure_stock(cart_item.variant, int(quantity))
        cart_item.quantity = int(quantity)

        db.flush()
        return CartService._build_cart_response(db, cart_item.cart)

    @staticmethod
    def delete_item(db: Session, *, user_id: UUID, item_id: UUID) -> CartResponse:
        cart_item = (
            db.query(CartItem)
            .join(Cart, CartItem.cart_id == Cart.id)
            .filter(CartItem.id == item_id, Cart.user_id == user_id)
            .first()
        )

        if cart_item is None:
            raise HTTPException(status_code=404, detail="Cart item not found")

        cart = cart_item.cart
        db.delete(cart_item)
        db.flush()

        return CartService._build_cart_response(db, cart)

    @staticmethod
    def merge_guest_items(
        db: Session,
        *,
        user_id: UUID,
        guest_items: list[dict[str, UUID | int]],
    ) -> CartResponse:
        cart = CartService._get_or_create_user_cart(db, user_id=user_id)

        consolidated: dict[tuple[UUID, UUID], int] = defaultdict(int)
        for guest_item in guest_items:
            product_id = guest_item.get("product_id")
            variant_id = guest_item.get("variant_id")
            quantity = int(guest_item.get("quantity") or 0)

            if not isinstance(product_id, UUID) or not isinstance(variant_id, UUID):
                continue

            if quantity <= 0:
                continue

            consolidated[(product_id, variant_id)] += quantity

        if not consolidated:
            return CartService._build_cart_response(db, cart)

        existing_items = (
            db.query(CartItem)
            .filter(CartItem.cart_id == cart.id)
            .all()
        )
        existing_by_key = {
            (item.product_id, item.variant_id): item
            for item in existing_items
        }

        for (product_id, variant_id), quantity in consolidated.items():
            _, variant = CartService._validate_product_variant(db, product_id=product_id, variant_id=variant_id)
            existing_item = existing_by_key.get((product_id, variant_id))

            if existing_item is not None:
                next_quantity = int(existing_item.quantity) + int(quantity)
                CartService._ensure_stock(variant, next_quantity)
                existing_item.quantity = next_quantity
                continue

            CartService._ensure_stock(variant, int(quantity))
            created_item = CartItem(
                cart_id=cart.id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=int(quantity),
            )
            db.add(created_item)
            existing_by_key[(product_id, variant_id)] = created_item

        db.flush()
        return CartService._build_cart_response(db, cart)
