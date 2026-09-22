"""Task 05: storefront-facing code must never read the dropped `ProductVariant.size`
column. `ProductVariant.attribute_label` replaces it, joining the variant's linked
`AttributeValue.value` strings into a display label (e.g. "Ring Size 6, Ruby"), or
None for a variant with no attribute values (matches the old `size=None` behavior).

Uses SimpleNamespace stand-ins for the ORM relationship chain, same pattern as
tests/test_pricing_decimal.py — no DB needed, `attribute_label` is a pure property.
"""

from types import SimpleNamespace

from urjaa_core.models.product_variant import ProductVariant

# `attribute_label` is a plain-python property that only reads self.attribute_values,
# so it's exercised via the unbound property against a SimpleNamespace stand-in rather
# than a real ProductVariant() instance — assigning a list of SimpleNamespace items to
# an actual SQLAlchemy-instrumented relationship attribute raises, since the ORM
# expects real mapped instances (not needed here; nothing touches the DB).
_attribute_label = ProductVariant.attribute_label.fget


def make_variant(attribute_values):
    return SimpleNamespace(attribute_values=attribute_values)


def va(value):
    return SimpleNamespace(attribute_value=SimpleNamespace(value=value))


def test_attribute_label_joins_multiple_values():
    variant = make_variant([va("Ring Size 6"), va("Ruby")])
    assert _attribute_label(variant) == "Ring Size 6, Ruby"


def test_attribute_label_single_value():
    variant = make_variant([va("Ring Size 6")])
    assert _attribute_label(variant) == "Ring Size 6"


def test_attribute_label_none_when_no_attribute_values():
    variant = make_variant([])
    assert _attribute_label(variant) is None


def test_attribute_label_skips_dangling_links():
    # defensive: a VariantAttribute row with no linked AttributeValue (or an
    # empty value) must not crash or produce an empty string in the join
    variant = make_variant([va(None), va("Ruby"), SimpleNamespace(attribute_value=None)])
    assert _attribute_label(variant) == "Ruby"


if __name__ == "__main__":
    test_attribute_label_joins_multiple_values()
    test_attribute_label_single_value()
    test_attribute_label_none_when_no_attribute_values()
    test_attribute_label_skips_dangling_links()
    print("ok")
