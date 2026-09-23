"""`create_variant`/`update_variant` must turn a raw SQLAlchemy IntegrityError
(DB CHECK/UNIQUE constraint violation) into a specific, readable 422 detail
instead of letting it bubble up as an unstructured 500 (see
docs/feature-additions-2026-09-19/variant-error-handling/TICKET.md).

`_variant_integrity_error_detail` is a pure function of the exception, so it's
exercised directly with SimpleNamespace stand-ins for `IntegrityError.orig`
(psycopg2's `.diag.constraint_name`), same no-DB pattern as
tests/test_variant_attribute_label.py.
"""

from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from urjaa_core.services.admin.admin_management_service import AdminManagementService

_detail = AdminManagementService._variant_integrity_error_detail


class OrigStub:
    """Stand-in for psycopg2's IntegrityError.orig: __str__ carries the raw
    Postgres error text, .diag.constraint_name carries the parsed name (when
    the driver provides it)."""

    def __init__(self, message="", constraint_name=None):
        self._message = message
        self.diag = SimpleNamespace(constraint_name=constraint_name) if constraint_name else SimpleNamespace()

    def __str__(self):
        return self._message


def test_known_constraint_via_diag_attribute():
    exc = IntegrityError("stmt", {}, OrigStub(constraint_name="chk_variant_weight_positive"))
    assert "Weight" in _detail(exc)


def test_known_constraint_via_message_fallback():
    orig = OrigStub(message='violates check constraint "chk_variant_making_non_negative"')
    exc = IntegrityError("stmt", {}, orig)
    assert _detail(exc) == "Making charges cannot be negative"


def test_duplicate_sku_maps_to_readable_message():
    exc = IntegrityError("stmt", {}, OrigStub(constraint_name="product_variants_sku_code_key"))
    assert _detail(exc) == "Variant SKU already exists"


def test_unmapped_constraint_falls_back_to_generic_message():
    exc = IntegrityError("stmt", {}, OrigStub(constraint_name="some_future_constraint_nobody_mapped_yet"))
    assert _detail(exc) == "Invalid variant data — check numeric fields are valid"


if __name__ == "__main__":
    test_known_constraint_via_diag_attribute()
    test_known_constraint_via_message_fallback()
    test_duplicate_sku_maps_to_readable_message()
    test_unmapped_constraint_falls_back_to_generic_message()
    print("ok")
