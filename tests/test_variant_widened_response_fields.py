"""B-01: VariantResponse widening adds base_metal_name/metal_color_name/
metal_purity_label properties to ProductVariant, and a `name` property to
ProductStone (pulled from the related Stone), so the storefront-facing
schemas can serialize them via plain orm_mode attribute lookup — same
pattern as the existing `attribute_label` property.

Pure-property tests with SimpleNamespace stand-ins, same no-DB pattern as
tests/test_variant_attribute_label.py.
"""

from types import SimpleNamespace

from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.product_stone import ProductStone

_base_metal_name = ProductVariant.base_metal_name.fget
_metal_color_name = ProductVariant.metal_color_name.fget
_metal_purity_label = ProductVariant.metal_purity_label.fget
_stone_name = ProductStone.name.fget


def test_base_metal_name_present():
    variant = SimpleNamespace(base_metal=SimpleNamespace(name="Gold"))
    assert _base_metal_name(variant) == "Gold"


def test_base_metal_name_none_when_unset():
    variant = SimpleNamespace(base_metal=None)
    assert _base_metal_name(variant) is None


def test_metal_color_name_present():
    variant = SimpleNamespace(metal_color=SimpleNamespace(name="Yellow"))
    assert _metal_color_name(variant) == "Yellow"


def test_metal_color_name_none_when_unset():
    variant = SimpleNamespace(metal_color=None)
    assert _metal_color_name(variant) is None


def test_metal_purity_label_present():
    variant = SimpleNamespace(metal_purity=SimpleNamespace(purity_label="BIS 750 (18K)"))
    assert _metal_purity_label(variant) == "BIS 750 (18K)"


def test_metal_purity_label_none_when_unset():
    variant = SimpleNamespace(metal_purity=None)
    assert _metal_purity_label(variant) is None


def test_stone_name_present():
    product_stone = SimpleNamespace(stone=SimpleNamespace(name="Ruby"))
    assert _stone_name(product_stone) == "Ruby"


def test_stone_name_none_when_unset():
    product_stone = SimpleNamespace(stone=None)
    assert _stone_name(product_stone) is None


if __name__ == "__main__":
    test_base_metal_name_present()
    test_base_metal_name_none_when_unset()
    test_metal_color_name_present()
    test_metal_color_name_none_when_unset()
    test_metal_purity_label_present()
    test_metal_purity_label_none_when_unset()
    test_stone_name_present()
    test_stone_name_none_when_unset()
    print("ok")
