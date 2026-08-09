from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# URJ-066: label shown when a product/variant cannot be priced (missing metal
# rate). Read paths must render this instead of a misleading ₹0.
PRICE_ON_REQUEST = "Price on Request"


def format_price_or_request(amount: "Decimal | float | int | None") -> str:
    """Format a price, or return the shared "Price on Request" label when None."""
    if amount is None:
        return PRICE_ON_REQUEST
    return format_inr(amount)


def format_inr(amount: Decimal | float | int) -> str:
    """Returns Indian-formatted currency string like: ₹1,23,456."""
    try:
        decimal_value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        decimal_value = Decimal("0")

    rounded = decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    is_negative = rounded < 0
    absolute_value = abs(int(rounded))

    digits = str(absolute_value)
    if len(digits) <= 3:
        grouped = digits
    else:
        last_three = digits[-3:]
        remaining = digits[:-3]
        groups: list[str] = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        grouped = ",".join(groups + [last_three])

    prefix = "-₹" if is_negative else "₹"
    return f"{prefix}{grouped}"
