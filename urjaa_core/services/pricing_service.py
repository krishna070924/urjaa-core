import logging
import threading
from datetime import datetime, timedelta

from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.repositories.metal_rate_repository import MetalRateRepository

logger = logging.getLogger("uvicorn.error")

try:  # optional: surface pricing fallbacks in Sentry when it is configured
    import sentry_sdk
except ImportError:  # pragma: no cover - Sentry is not installed in this project
    sentry_sdk = None

# URJ-066: scalar metal-rate cache — {base_metal_id: (rate_float_or_None, ts)}.
# It must NEVER hold ORM objects. The previous cache stored MetalRate rows, which
# (a) leaked detached instances across request sessions (DetachedInstanceError ->
# HTTP 500) and (b) could serve a stale or None rate for up to the TTL, which made
# the failure flap even after an admin set the rate. Caching plain floats removes
# both hazards. A lock guards the check-then-set because FastAPI runs sync routes
# in a thread pool, so concurrent requests share this module-level dict.
_rate_cache: dict[int, tuple[float | None, datetime]] = {}
_rate_cache_ttl = timedelta(seconds=60)
_rate_cache_lock = threading.Lock()


def _get_cached_metal_rate(db, base_metal_id) -> float | None:
    """Return the latest effective metal rate as a float, or None if unavailable.

    A 60-second TTL scalar cache avoids an N+1 query when pricing a multi-item
    cart or a product list (one lookup per metal per minute, not one per variant).
    """
    now = datetime.utcnow()
    with _rate_cache_lock:
        cached = _rate_cache.get(base_metal_id)
        if cached is not None and (now - cached[1]) < _rate_cache_ttl:
            return cached[0]

    rate_row = MetalRateRepository.get_latest_rate(db, base_metal_id)
    rate_value = float(rate_row.rate_per_gram) if rate_row is not None else None

    with _rate_cache_lock:
        _rate_cache[base_metal_id] = (rate_value, now)
    return rate_value


def _report_pricing_fallback(variant, base_metal_id) -> None:
    """Log (and optionally Sentry-capture) that a variant could not be priced."""
    product_id = getattr(variant, "product_id", None)
    variant_id = getattr(variant, "id", None)
    logger.warning(
        "pricing_fallback: unpriceable variant, rendering Price on Request "
        "product_id=%s variant_id=%s base_metal_id=%s reason=missing_metal_rate",
        product_id,
        variant_id,
        base_metal_id,
    )
    if sentry_sdk is not None:  # pragma: no cover - only runs when Sentry configured
        try:
            sentry_sdk.capture_message(
                f"pricing_fallback: missing metal rate "
                f"(product_id={product_id}, base_metal_id={base_metal_id})",
                level="warning",
            )
        except Exception:
            pass


class PricingService:

    @staticmethod
    def calculate_variant_price(variant, db, rate_cache: dict | None = None) -> float | None:
        """Price one variant, or return None when it cannot be priced.

        URJ-066: a missing metal rate no longer raises. Read paths (list/PDP/cart)
        treat None as "Price on Request"; checkout/order-creation treat None as a
        hard error and refuse to create a mispriced order.
        """
        override = getattr(variant, "price_override", None)
        if override is not None:
            return max(float(override), 0.0)

        base_metal_id = variant.base_metal_id

        # The per-request rate_cache may legitimately cache a None (no rate), so we
        # test membership rather than truthiness to avoid re-querying every item.
        if rate_cache is not None and base_metal_id in rate_cache:
            metal_rate = rate_cache[base_metal_id]
        else:
            metal_rate = _get_cached_metal_rate(db, base_metal_id)
            if rate_cache is not None:
                rate_cache[base_metal_id] = metal_rate

        if metal_rate is None:
            _report_pricing_fallback(variant, base_metal_id)
            return None

        rate = float(metal_rate)

        purity_factor = 1.0
        purity = getattr(variant, "metal_purity", None)
        if purity is not None and getattr(purity, "numeric_purity", None) is not None:
            purity_factor = float(purity.numeric_purity) / 100
        elif getattr(variant, "metal_purity_id", None):
            purity_row = db.query(MetalPurity).filter(MetalPurity.id == variant.metal_purity_id).first()
            if purity_row and purity_row.numeric_purity is not None:
                purity_factor = float(purity_row.numeric_purity) / 100

        adjusted_rate = rate * purity_factor

        weight = float(variant.metal_weight_grams or 0)
        stone = float(variant.stone_cost or 0)
        making = float(variant.making_charges or 0)

        computed_price = (weight * adjusted_rate) + stone + making
        return max(computed_price, 0.0)

    @staticmethod
    def calculate_product_starting_price(product, db, rate_cache: dict | None = None) -> float | None:
        """Return the lowest priceable variant price, or None if none can be priced."""
        if not product or not product.variants:
            return None

        prices: list[float] = []
        for variant in product.variants:
            price = PricingService.calculate_variant_price(variant, db, rate_cache=rate_cache)
            if price is not None:
                prices.append(price)

        return min(prices) if prices else None
