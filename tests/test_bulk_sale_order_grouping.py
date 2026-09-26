"""Task 01 self-check: SalesService.create_bulk_sale must group a multi-item
walk-in basket into one Order (so a single combined invoice exists), stamp
every Sale in the batch with that order_id, and generate invoice numbers via
a real Postgres-atomic per-store-per-month counter (no lost updates under
concurrency).

Integration test against the live dev Postgres (DATABASE_URL from env/.env,
same DB the app uses) -- no mocking the ORM, no sqlite. Creates its own
throwaway store/product/variants/metal-rate fixtures (existing dev DB has
zero stocked variants and zero metal rates to reuse) and deletes every row
it creates in a `finally` block.

Run: `python tests/test_bulk_sale_order_grouping.py` (DATABASE_URL must
already point at a migrated `urjaa` DB -- run `alembic upgrade head` first).
"""

import base64
import os
import re
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urjaa_core.core.database import SessionLocal  # noqa: E402
from urjaa_core.models.base_metal import BaseMetal  # noqa: E402
from urjaa_core.models.metal_rate import MetalRate  # noqa: E402
from urjaa_core.models.order import Order  # noqa: E402
from urjaa_core.models.product import Product  # noqa: E402
from urjaa_core.models.product_variant import ProductVariant  # noqa: E402
from urjaa_core.models.sale import Sale  # noqa: E402
from urjaa_core.models.store import Store  # noqa: E402
from urjaa_core.schemas.admin.sales import BulkSaleCreateRequest, BulkSaleItemRequest  # noqa: E402
from urjaa_core.services.admin.sales_service import SalesService  # noqa: E402

UTC = timezone.utc


def _build_fixtures(db):
    """Create a throwaway store + a stocked, priceable product/variant set."""
    store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
    db.add(store)

    base_metal = BaseMetal(name=f"TestGold-{uuid4().hex[:6]}")
    db.add(base_metal)
    db.flush()

    metal_rate = MetalRate(base_metal_id=base_metal.id, rate_per_gram=Decimal("5000.00"), effective_from=datetime.now(UTC))
    db.add(metal_rate)

    product = Product(id=uuid4(), store_id=store.id, name="Test Ring", slug=f"test-ring-{uuid4().hex[:8]}", status="active")
    db.add(product)
    db.flush()

    variants = []
    for i in range(3):
        variant = ProductVariant(
            id=uuid4(),
            store_id=store.id,
            product_id=product.id,
            base_metal_id=base_metal.id,
            metal_type=base_metal.name,
            weight=Decimal("2.000"),
            making_charges=Decimal("100.00"),
            stock_quantity=10,
            sku_code=f"TEST-SKU-{uuid4().hex[:10]}",
            status="active",
        )
        db.add(variant)
        variants.append(variant)
    db.commit()
    return store, product, variants


def _cleanup(db, store, product, variants, base_metal, metal_rate, sale_ids, order_ids):
    db.rollback()
    db.query(Sale).filter(Sale.id.in_(sale_ids)).delete(synchronize_session=False)
    db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
    db.query(ProductVariant).filter(ProductVariant.id.in_([v.id for v in variants])).delete(synchronize_session=False)
    db.query(Product).filter(Product.id == product.id).delete(synchronize_session=False)
    db.query(MetalRate).filter(MetalRate.id == metal_rate.id).delete(synchronize_session=False)
    db.query(BaseMetal).filter(BaseMetal.id == base_metal.id).delete(synchronize_session=False)
    db.execute(text("DELETE FROM invoice_sequences WHERE store_id = :sid"), {"sid": store.id})
    db.query(Store).filter(Store.id == store.id).delete(synchronize_session=False)
    db.commit()


def test_bulk_sale_groups_into_one_order():
    db = SessionLocal()
    sale_ids: list = []
    order_ids: list = []
    store = product = variants = base_metal = metal_rate = None
    try:
        store, product, variants = _build_fixtures(db)
        base_metal = variants[0].base_metal
        metal_rate = db.query(MetalRate).filter(MetalRate.base_metal_id == base_metal.id).first()

        payload = BulkSaleCreateRequest(
            items=[
                BulkSaleItemRequest(product_id=product.id, variant_id=v.id, quantity=1, final_price=15000.00)
                for v in variants
            ]
        )
        result = SalesService.create_bulk_sale(db, store_id=store.id, payload=payload)
        sale_ids.extend(result["created_sale_ids"])
        order_ids.append(result["order_id"])

        assert result["order_id"] is not None, "create_bulk_sale must return an order_id"
        assert len(result["created_sale_ids"]) == 3

        order = db.query(Order).filter(Order.id == result["order_id"]).one()
        assert order.status == "COMPLETED", order.status
        assert order.source == "store", order.source
        assert order.invoice_number is not None

        sales = db.query(Sale).filter(Sale.id.in_(result["created_sale_ids"])).all()
        assert len(sales) == 3
        assert {s.order_id for s in sales} == {order.id}

        # Second bulk sale in same store/month -> sequential, non-colliding invoice number.
        payload2 = BulkSaleCreateRequest(
            items=[BulkSaleItemRequest(product_id=product.id, variant_id=variants[0].id, quantity=1, final_price=1000.00)]
        )
        result2 = SalesService.create_bulk_sale(db, store_id=store.id, payload=payload2)
        sale_ids.extend(result2["created_sale_ids"])
        order_ids.append(result2["order_id"])
        order2 = db.query(Order).filter(Order.id == result2["order_id"]).one()

        assert order.invoice_number != order2.invoice_number
        seq1 = int(order.invoice_number.rsplit("-", 1)[1])
        seq2 = int(order2.invoice_number.rsplit("-", 1)[1])
        assert seq2 == seq1 + 1, (order.invoice_number, order2.invoice_number)

        print(f"OK: order {order.id} groups 3 sales, invoice_number={order.invoice_number}")
        print(f"OK: sequential invoice numbers {order.invoice_number} -> {order2.invoice_number}")
    finally:
        if store is not None:
            _cleanup(db, store, product, variants, base_metal, metal_rate, sale_ids, order_ids)
        db.close()


def test_invoice_number_sequence_is_race_free():
    """Real concurrency: N threads, each its own DB session, all incrementing
    the same (store_id, period) counter at once. Assert no duplicate/lost seq.
    """
    db = SessionLocal()
    sale_ids: list = []
    order_ids: list = []
    store = product = variants = base_metal = metal_rate = None
    try:
        store, product, variants = _build_fixtures(db)
        base_metal = variants[0].base_metal
        metal_rate = db.query(MetalRate).filter(MetalRate.base_metal_id == base_metal.id).first()

        N = 12
        # Capture plain UUIDs before threading -- the ORM objects are bound to
        # `db`'s session, which isn't thread-safe to touch from worker threads.
        store_id = store.id
        product_id = product.id
        variant_id = variants[0].id

        def _one_bulk_sale(_):
            thread_db = SessionLocal()
            try:
                payload = BulkSaleCreateRequest(
                    items=[BulkSaleItemRequest(product_id=product_id, variant_id=variant_id, quantity=1, final_price=1.0)]
                )
                result = SalesService.create_bulk_sale(thread_db, store_id=store_id, payload=payload)
                return result
            finally:
                thread_db.close()

        # Give enough stock for N concurrent 1-unit sales against the same variant.
        db.query(ProductVariant).filter(ProductVariant.id == variant_id).update({"stock_quantity": N + 1})
        db.commit()

        results = []
        with ThreadPoolExecutor(max_workers=N) as pool:
            futures = [pool.submit(_one_bulk_sale, i) for i in range(N)]
            for f in as_completed(futures):
                results.append(f.result())

        for r in results:
            sale_ids.extend(r["created_sale_ids"])
            order_ids.append(r["order_id"])

        invoice_numbers = [
            row[0] for row in db.query(Order.invoice_number).filter(Order.id.in_(order_ids)).all()
        ]
        assert len(invoice_numbers) == N
        assert len(set(invoice_numbers)) == N, f"duplicate invoice numbers under concurrency: {invoice_numbers}"

        seqs = sorted(int(n.rsplit("-", 1)[1]) for n in invoice_numbers)
        assert seqs == list(range(seqs[0], seqs[0] + N)), f"gaps/dupes in sequence: {seqs}"

        print(f"OK: {N} concurrent bulk sales produced {N} unique, gapless invoice numbers: {seqs}")
    finally:
        if store is not None:
            _cleanup(db, store, product, variants, base_metal, metal_rate, sale_ids, order_ids)
        db.close()


def test_invoice_sequence_upsert_is_atomic_under_raw_concurrency():
    """Direct hammer on SalesService._generate_order_invoice_number itself
    (bypassing the variant row lock create_bulk_sale also takes), to prove
    the ON CONFLICT ... DO UPDATE ... RETURNING seq upsert alone is race-free.
    """
    db = SessionLocal()
    store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
    store_id = store.id
    N = 20
    when = datetime.now(UTC)
    try:
        db.add(store)
        db.commit()

        def _one(_):
            thread_db = SessionLocal()
            try:
                with thread_db.begin():
                    return SalesService._generate_order_invoice_number(thread_db, store_id, when)
            finally:
                thread_db.close()

        with ThreadPoolExecutor(max_workers=N) as pool:
            numbers = list(pool.map(_one, range(N)))

        assert len(set(numbers)) == N, f"duplicate invoice numbers: {numbers}"
        seqs = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
        assert seqs == list(range(1, N + 1)), f"gaps/dupes in raw upsert sequence: {seqs}"
        print(f"OK: {N} concurrent raw upserts produced unique gapless seqs {seqs[0]}..{seqs[-1]}")
    finally:
        db.rollback()
        db.execute(text("DELETE FROM invoice_sequences WHERE store_id = :sid"), {"sid": store.id})
        db.query(Store).filter(Store.id == store.id).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_online_checkout_order_path_unaffected():
    """Order rows created without an explicit `source` (the online-checkout
    path in order_service.py / checkout_service.py) still default to
    'website' and keep their normal PENDING lifecycle status.
    """
    db = SessionLocal()
    store = Store(id=uuid4(), name=f"Test Store {uuid4().hex[:6]}")
    order = Order(
        store_id=store.id,
        email="customer@example.com",
        full_name="Website Customer",
        total_amount=Decimal("100.00"),
        status="PENDING",
    )
    try:
        db.add(store)
        db.add(order)
        db.commit()
        db.refresh(order)
        assert order.source == "website", order.source
        assert order.status == "PENDING"
        print(f"OK: online-checkout Order defaults source={order.source!r} status={order.status!r}")
    finally:
        db.rollback()
        db.query(Order).filter(Order.id == order.id).delete(synchronize_session=False)
        db.query(Store).filter(Store.id == store.id).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_build_invoice_pdf_covers_all_order_lines():
    """Task 02 self-check: a 3-item walk-in basket must produce ONE pdf
    covering all 3 lines + a correct grand total, keyed by order_id (not
    the old single-sale_id path).
    """
    db = SessionLocal()
    sale_ids: list = []
    order_ids: list = []
    store = product = variants = base_metal = metal_rate = None
    try:
        store, product, variants = _build_fixtures(db)
        base_metal = variants[0].base_metal
        metal_rate = db.query(MetalRate).filter(MetalRate.base_metal_id == base_metal.id).first()

        prices = [15000.00, 8000.00, 2500.00]
        payload = BulkSaleCreateRequest(
            items=[
                BulkSaleItemRequest(product_id=product.id, variant_id=v.id, quantity=1, final_price=p)
                for v, p in zip(variants, prices)
            ]
        )
        result = SalesService.create_bulk_sale(db, store_id=store.id, payload=payload)
        sale_ids.extend(result["created_sale_ids"])
        order_ids.append(result["order_id"])

        file_name, pdf_bytes = SalesService.build_invoice_pdf(db, store_id=store.id, order_id=result["order_id"])

        order = db.query(Order).filter(Order.id == result["order_id"]).one()
        assert pdf_bytes.startswith(b"%PDF"), "not a valid PDF"
        assert order.invoice_number in file_name
        assert file_name.endswith(".pdf")

        # Every line's SKU must appear in the rendered (ASCII85+Flate-encoded) content stream.
        content = b"".join(
            zlib.decompress(base64.a85decode(raw.rstrip(b"\r\n").removesuffix(b"~>")))
            for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.DOTALL)
        )
        for v in variants:
            assert v.sku_code.encode() in content, f"missing line for {v.sku_code}"

        expected_total = round(sum(prices), 2)
        assert round(float(order.total_amount), 2) == expected_total

        print(f"OK: invoice {order.invoice_number} for order {order.id} covers all 3 lines, total={expected_total}")
    finally:
        if store is not None:
            _cleanup(db, store, product, variants, base_metal, metal_rate, sale_ids, order_ids)
        db.close()


if __name__ == "__main__":
    test_bulk_sale_groups_into_one_order()
    test_invoice_number_sequence_is_race_free()
    test_invoice_sequence_upsert_is_atomic_under_raw_concurrency()
    test_online_checkout_order_path_unaffected()
    test_build_invoice_pdf_covers_all_order_lines()
    print("All self-checks passed.")
