"""M-8: money math must run entirely in Decimal, rounded once (ROUND_HALF_UP) at each
final-price boundary, never in float with per-step round().

These tests exercise pure functions only (PricingService.calculate_variant_price and
the round_money helper) with SimpleNamespace stand-ins for ORM objects — no DB needed,
since calculate_variant_price never touches `db` when the metal rate is pre-seeded into
`rate_cache`.

Coverage note: checkout_service.create_order / order_service.create_order_from_cart
themselves are DB-backed (they query Product/ProductVariant with row locks) and are not
exercised end-to-end here. Instead, test_checkout_total_accumulation_matches_service_logic
below replicates the exact accumulator pattern used in both services (round once per
line via round_money, then plain Decimal addition for the running total) and proves it
sums exactly for inputs a float accumulator would drift on. That is the arithmetic this
bug fix changes; the surrounding DB/HTTP plumbing is unchanged by this fix.
"""

from decimal import Decimal, ROUND_HALF_EVEN
from types import SimpleNamespace

from urjaa_core.services.pricing_service import PricingService, round_money


def make_variant(
    *,
    price_override=None,
    base_metal_id=1,
    numeric_purity=None,
    metal_weight_grams=Decimal("0"),
    stone_cost=Decimal("0"),
    making_charges=Decimal("0"),
):
    metal_purity = None
    if numeric_purity is not None:
        metal_purity = SimpleNamespace(numeric_purity=numeric_purity)
    return SimpleNamespace(
        id="variant-1",
        product_id="product-1",
        price_override=price_override,
        base_metal_id=base_metal_id,
        metal_purity=metal_purity,
        metal_purity_id=None,
        metal_weight_grams=metal_weight_grams,
        stone_cost=stone_cost,
        making_charges=making_charges,
    )


# 1. Exact-Decimal computation -----------------------------------------------------

def test_calculate_variant_price_exact_decimal_result():
    variant = make_variant(
        base_metal_id=1,
        numeric_purity=Decimal("91.600"),  # 22K gold
        metal_weight_grams=Decimal("10.500"),
        stone_cost=Decimal("500.00"),
        making_charges=Decimal("1200.25"),
    )
    rate_cache = {1: Decimal("6000.00")}

    price = PricingService.calculate_variant_price(variant, db=None, rate_cache=rate_cache)

    # weight(10.500) * (6000.00 * 0.916) + 500.00 + 1200.25 = 59408.25 exactly.
    assert price == Decimal("59408.25")
    assert isinstance(price, Decimal)


def test_calculate_variant_price_uses_price_override_and_rounds_once():
    variant = make_variant(price_override=Decimal("12345.678"))

    price = PricingService.calculate_variant_price(variant, db=None, rate_cache={})

    assert price == Decimal("12345.68")  # ROUND_HALF_UP at the single rounding point


def test_calculate_variant_price_returns_none_when_rate_missing():
    variant = make_variant(base_metal_id=1, numeric_purity=Decimal("91.600"))
    rate_cache = {1: None}  # membership test: a cached None means "no rate", not "look it up"

    price = PricingService.calculate_variant_price(variant, db=None, rate_cache=rate_cache)

    assert price is None


# 2. Decimal accumulation is exact where float accumulation would drift ------------

def test_decimal_accumulation_is_exact_where_float_drifts():
    # Classic float trap: three 0.1s don't sum to exactly 0.3 in binary float
    # (0.1 has no exact binary representation, and unlike the sum-of-ten case the
    # rounding errors here don't cancel out).
    float_total = sum([0.1] * 3)
    assert float_total != 0.3  # demonstrates the old bug's failure mode

    # Three variants each priced (via override) at 0.10 — same shape, Decimal path.
    decimal_total = Decimal("0")
    for _ in range(3):
        variant = make_variant(price_override=Decimal("0.10"))
        price = PricingService.calculate_variant_price(variant, db=None, rate_cache={})
        decimal_total += price  # each price already rounded once; addition is exact

    assert decimal_total == Decimal("0.30")


# 3. ROUND_HALF_UP is actually in effect, not Python's default ROUND_HALF_EVEN -----

def test_round_money_uses_round_half_up_not_banker_rounding():
    value = Decimal("2.665")  # exact halfway point between 2.66 and 2.67

    half_even = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    half_up = round_money(value)

    assert half_even == Decimal("2.66")  # banker's rounding: rounds to the even digit
    assert half_up == Decimal("2.67")  # round_money: always rounds the halfway case up
    assert half_up != half_even


# 4. Same accumulator pattern used in checkout_service.create_order /
#    order_service.create_order_from_cart, tested in isolation (no DB) -------------

def test_checkout_total_accumulation_matches_service_logic():
    # Mirrors: line_total = round_money(unit_price * quantity); total += line_total
    # (checkout_service.py / order_service.py, post-fix).
    line_items = [
        (Decimal("59408.25"), 3),   # line_total = 178224.75
        (Decimal("0.10"), 7),       # line_total = 0.70
        (Decimal("999.99"), 2),     # line_total = 1999.98
    ]

    total_amount = Decimal("0")
    line_totals = []
    for unit_price, quantity in line_items:
        line_total = round_money(unit_price * quantity)
        line_totals.append(line_total)
        total_amount = total_amount + line_total  # exact: both operands already 2dp

    assert line_totals == [Decimal("178224.75"), Decimal("0.70"), Decimal("1999.98")]
    assert total_amount == Decimal("180225.43")
    # Sanity: plain Decimal addition of already-rounded values needs no extra rounding.
    assert total_amount == round_money(total_amount)
