"""H-07 self-check against the live dev database, as the admin app role.
The service commits internally, so the session is joined to an outer
transaction via savepoints and everything is rolled back at the end.

Run: .venv/bin/python tests/test_metal_generator.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import BaseMetal, MetalColor, MetalPurity, ProductVariant, Store
from urjaa_core.schemas.admin.management import MetalCombinationGenerateRequest
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        gold = db.query(BaseMetal).filter(BaseMetal.name == "Gold").first()
        silver = db.query(BaseMetal).filter(BaseMetal.name == "Silver").first()
        assert gold and silver, "seed catalogue missing Gold/Silver base metals"

        white = db.query(MetalColor).filter(MetalColor.name == "White", MetalColor.base_metal_id == gold.id).first()
        rose = db.query(MetalColor).filter(MetalColor.name == "Rose", MetalColor.base_metal_id == gold.id).first()
        silver_colour = db.query(MetalColor).filter(MetalColor.base_metal_id == silver.id).first()
        purity_24k = (
            db.query(MetalPurity)
            .filter(MetalPurity.base_metal_id == gold.id, MetalPurity.purity_label == "24K")
            .first()
        )
        assert white and rose and silver_colour and purity_24k, "seed catalogue missing expected colours/purities"

        # 1. Generating creates the missing combinations. (Gold 24K White/Rose
        # are not in scripts/seed_dev_catalogue.sql — only 22K/18K/14K are.)
        payload = MetalCombinationGenerateRequest(
            base_metal_id=gold.id, metal_color_ids=[white.id, rose.id], metal_purity_ids=[purity_24k.id]
        )
        created, skipped = svc.generate_metal_combinations(db, payload)
        assert len(created) == 2 and len(skipped) == 0, (created, skipped)
        names = {row["display_name"] for row in created}
        assert names == {"24K White Gold", "24K Rose Gold"}, names
        print(f"generate creates missing combos   OK  {sorted(names)}")

        # 2. Re-running the same request is idempotent: nothing new created,
        # both rows reported as skipped with the same ids as before.
        created2, skipped2 = svc.generate_metal_combinations(db, payload)
        assert len(created2) == 0 and len(skipped2) == 2, (created2, skipped2)
        assert {row["id"] for row in skipped2} == {row["id"] for row in created}
        print("re-run is idempotent (0 created)  OK")

        # 3. A colour that belongs to a different base metal is rejected.
        try:
            svc.generate_metal_combinations(
                db,
                MetalCombinationGenerateRequest(
                    base_metal_id=gold.id, metal_color_ids=[silver_colour.id], metal_purity_ids=[purity_24k.id]
                ),
            )
            raise AssertionError("mismatched colour accepted")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.status_code
        print("colour from another base metal    OK  rejected 422")

        # 4. Deleting a combination a variant references is refused.
        store = db.query(Store).first()
        referenced_id = created[0]["id"]
        db.add(ProductVariant(store_id=store.id, metal_id=referenced_id))
        db.flush()
        try:
            svc.delete_metal_combination(db, referenced_id)
            raise AssertionError("referenced combination deleted")
        except HTTPException as exc:
            assert exc.status_code == 409, exc.status_code
        print("delete of referenced combo        OK  rejected 409")

        # Sanity: an unreferenced combination deletes cleanly.
        svc.delete_metal_combination(db, created[1]["id"])
        print("delete of unreferenced combo      OK")

        print("ALL OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
