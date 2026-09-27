"""B-02 self-check: product_stones gains six nullable certification columns
(cut/clarity/color/origin/certificate_number/certification_agency), and
`certification_agency` is constrained at the DB level to GIA/IGI/HRD/BIS.

Decision D3 (never required to create a product or variant) is the explicit
"write an actual check" requirement from the ticket -- proven here by
creating a product+variant with zero certification data, then a stone
attached with zero certification data, and confirming both commit clean.

Integration test against the live dev Postgres (DATABASE_URL from env/.env),
same pattern as tests/test_bulk_sale_order_grouping.py -- no mocking the ORM,
no sqlite. Creates its own throwaway store/product/variant/stone fixtures and
deletes every row it creates in a `finally` block.

Run: `python tests/test_product_stone_certification.py` (DATABASE_URL must
already point at a migrated `urjaa` DB -- run `alembic upgrade head` first).
"""

import os
import sys
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urjaa_core.core.database import SessionLocal  # noqa: E402
from urjaa_core.models.product import Product  # noqa: E402
from urjaa_core.models.product_stone import ProductStone  # noqa: E402
from urjaa_core.models.product_variant import ProductVariant  # noqa: E402
from urjaa_core.models.stone import Stone  # noqa: E402
from urjaa_core.models.store import Store  # noqa: E402
from urjaa_core.schemas.product import ProductDetailResponse  # noqa: E402
from urjaa_core.services.product_service import ProductService  # noqa: E402


def _cleanup(db, store, product, stone):
    db.rollback()
    if product is not None:
        db.query(ProductStone).filter(ProductStone.product_id == product.id).delete(synchronize_session=False)
        db.query(ProductVariant).filter(ProductVariant.product_id == product.id).delete(synchronize_session=False)
        db.query(Product).filter(Product.id == product.id).delete(synchronize_session=False)
    if stone is not None:
        db.query(Stone).filter(Stone.id == stone.id).delete(synchronize_session=False)
    if store is not None:
        db.query(Store).filter(Store.id == store.id).delete(synchronize_session=False)
    db.commit()


def test_product_variant_and_stone_create_clean_without_certification_data():
    """D3: no certification field is ever required. A product, a variant, and
    a stone attachment all created with every new column absent must commit."""
    db = SessionLocal()
    store = product = stone = None
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)

        product = Product(
            id=uuid4(),
            store_id=store.id,
            name="Test Ring",
            slug=f"test-ring-{uuid4().hex[:8]}",
            status="active",
        )
        db.add(product)
        db.flush()

        variant = ProductVariant(
            id=uuid4(),
            store_id=store.id,
            product_id=product.id,
            stock_quantity=5,
            sku_code=f"TEST-SKU-{uuid4().hex[:10]}",
            status="active",
        )
        db.add(variant)

        stone = Stone(name=f"TestStone-{uuid4().hex[:6]}")
        db.add(stone)
        db.flush()

        product_stone = ProductStone(product_id=product.id, stone_id=stone.id, quantity=1, total_carat_weight=1.5)
        db.add(product_stone)
        db.commit()

        db.refresh(product_stone)
        assert product_stone.cut is None
        assert product_stone.clarity is None
        assert product_stone.color is None
        assert product_stone.origin is None
        assert product_stone.certificate_number is None
        assert product_stone.certification_agency is None
        print("OK: product/variant/stone created with no certification data")
    finally:
        _cleanup(db, store, product, stone)
        db.close()


def test_invalid_certification_agency_rejected_by_db_constraint():
    """Acceptance criterion: an invalid certification_agency is rejected --
    enforced by chk_product_stones_certification_agency, not app code."""
    db = SessionLocal()
    store = product = stone = None
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)
        product = Product(id=uuid4(), store_id=store.id, name="Test Ring", slug=f"test-ring-{uuid4().hex[:8]}", status="active")
        db.add(product)
        stone = Stone(name=f"TestStone-{uuid4().hex[:6]}")
        db.add(stone)
        db.flush()

        db.add(ProductStone(product_id=product.id, stone_id=stone.id, certification_agency="FAKE"))
        raised = False
        try:
            db.commit()
        except IntegrityError as exc:
            raised = True
            assert "chk_product_stones_certification_agency" in str(exc.orig), exc.orig
        assert raised, "expected IntegrityError for an invalid certification_agency"
        print("OK: invalid certification_agency rejected by DB constraint")
    finally:
        _cleanup(db, store, product, stone)
        db.close()


def test_certification_appears_on_product_detail_response():
    """Acceptance criterion: certification appears on GET /products/{slug}
    when present. ProductService.get_product is the exact function the
    products.py route calls; ProductDetailResponse.from_orm is the exact
    schema the route serializes with."""
    db = SessionLocal()
    store = product = stone = None
    try:
        store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
        db.add(store)
        slug = f"test-ring-{uuid4().hex[:8]}"
        product = Product(id=uuid4(), store_id=store.id, name="Test Ring", slug=slug, status="active")
        db.add(product)
        stone = Stone(name=f"Diamond-{uuid4().hex[:6]}")
        db.add(stone)
        db.flush()

        db.add(
            ProductStone(
                product_id=product.id,
                stone_id=stone.id,
                quantity=1,
                total_carat_weight=1.2,
                cut="Round Brilliant",
                clarity="VVS1",
                color="D",
                origin="Botswana",
                certificate_number="GIA-1234567890",
                certification_agency="GIA",
            )
        )
        db.commit()

        fetched = ProductService.get_product(db, store_id=store.id, slug=slug)
        # model_validate(..., from_attributes=True) rather than .from_orm():
        # this repo's schemas declare `class Config: orm_mode = True` (pydantic
        # v1 style), which pydantic v2 no longer maps to from_attributes on its
        # own -- FastAPI's actual response serialization passes from_attributes
        # explicitly at validate time, same as here, so .from_orm() alone would
        # fail this test over a harness quirk unrelated to B-02.
        response = ProductDetailResponse.model_validate(fetched, from_attributes=True)
        stone_out = response.stones[0]
        assert stone_out.certification_agency == "GIA", stone_out
        assert stone_out.certificate_number == "GIA-1234567890", stone_out
        assert stone_out.cut == "Round Brilliant", stone_out
        assert stone_out.clarity == "VVS1", stone_out
        assert stone_out.color == "D", stone_out
        assert stone_out.origin == "Botswana", stone_out
        print(f"OK: certification present on ProductDetailResponse.stones: {stone_out}")
    finally:
        _cleanup(db, store, product, stone)
        db.close()


if __name__ == "__main__":
    test_product_variant_and_stone_create_clean_without_certification_data()
    test_invalid_certification_agency_rejected_by_db_constraint()
    test_certification_appears_on_product_detail_response()
    print("ALL OK")
