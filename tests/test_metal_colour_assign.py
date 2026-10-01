"""K-02 self-check against the live dev database, as the admin app role.
The service commits internally, so the session is joined to an outer
transaction via savepoints and everything is rolled back at the end.

Run: .venv/bin/python tests/test_metal_colour_assign.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine
from urjaa_core.models import BaseMetal, Metal, MetalColor, MetalPurity, ProductVariant, Store
from urjaa_core.schemas.admin.management import MetalColorCreateRequest, MetalColorUpdateRequest
from urjaa_core.services.admin.admin_management_service import AdminManagementService as svc


def main() -> None:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        db.execute(text("SET ROLE urjaa_admin_svc"))

        gold = db.query(BaseMetal).filter(BaseMetal.name == "Gold").first()
        silver = db.query(BaseMetal).filter(BaseMetal.name == "Silver").first()
        platinum = db.query(BaseMetal).filter(BaseMetal.name == "Platinum").first()
        assert gold and silver and platinum, "seed catalogue missing Gold/Silver/Platinum base metals"

        # 1. Create requires base_metal_id and succeeds with a valid one.
        created = svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=gold.id, name="K02 Test Colour"))
        assert created.base_metal_id == gold.id, created.base_metal_id
        print(f"create with base metal              OK  id={created.id} base_metal_id={created.base_metal_id}")

        # 2. Missing base_metal_id is rejected by the schema itself (required field).
        try:
            MetalColorCreateRequest(name="No Base Metal")
            raise AssertionError("base_metal_id-less create accepted")
        except ValidationError:
            pass
        print("create without base_metal_id        OK  rejected (pydantic, required)")

        # 3. Unknown base_metal_id is rejected with a readable 404.
        try:
            svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=999999, name="Ghost Metal Colour"))
            raise AssertionError("unknown base_metal_id accepted")
        except HTTPException as exc:
            assert exc.status_code == 404, exc.status_code
        print("create with unknown base metal      OK  rejected 404")

        # 4. Reassigning a colour that a `metals` combination uses is blocked.
        used_colour = svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=gold.id, name="K02 Used Colour"))
        gold_24k = (
            db.query(MetalPurity)
            .filter(MetalPurity.base_metal_id == gold.id, MetalPurity.purity_label == "24K")
            .first()
        )
        assert gold_24k, "seed catalogue missing Gold 24K purity"
        db.add(
            Metal(
                base_metal_id=gold.id,
                metal_color_id=used_colour.id,
                metal_purity_id=gold_24k.id,
                display_name="24K K02 Used Colour Gold",
            )
        )
        db.flush()
        try:
            svc.update_metal_color(db, used_colour.id, MetalColorUpdateRequest(base_metal_id=silver.id))
            raise AssertionError("reassign of combination-referenced colour accepted")
        except HTTPException as exc:
            assert exc.status_code == 409, exc.status_code
        print("reassign blocked (combo in use)     OK  rejected 409")

        # 5. A colour referenced only via a variant's legacy FK (no combo row) is also blocked.
        variant_colour = svc.create_metal_color(
            db, MetalColorCreateRequest(base_metal_id=gold.id, name="K02 Variant Colour")
        )
        store = db.query(Store).first()
        assert store, "seed catalogue missing a store"
        db.add(ProductVariant(store_id=store.id, metal_color_id=variant_colour.id))
        db.flush()
        try:
            svc.update_metal_color(db, variant_colour.id, MetalColorUpdateRequest(base_metal_id=platinum.id))
            raise AssertionError("reassign of variant-referenced colour accepted")
        except HTTPException as exc:
            assert exc.status_code == 409, exc.status_code
        print("reassign blocked (variant in use)   OK  rejected 409")

        # 6. Reassigning an unused colour is allowed.
        unused_colour = svc.create_metal_color(
            db, MetalColorCreateRequest(base_metal_id=gold.id, name="K02 Unused Colour")
        )
        updated = svc.update_metal_color(db, unused_colour.id, MetalColorUpdateRequest(base_metal_id=platinum.id))
        assert updated.base_metal_id == platinum.id, updated.base_metal_id
        print("reassign allowed (unused)           OK  base_metal_id now Platinum")

        # 7. Same name is allowed under two different base metals (uniqueness is
        # scoped per base metal, not global — see repository docstring note).
        svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=platinum.id, name="K02 Shared Name"))
        reused = svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=silver.id, name="K02 Shared Name"))
        assert reused.base_metal_id == silver.id
        print("same name under two base metals     OK  allowed")

        # 8. Same name under the SAME base metal is still rejected.
        try:
            svc.create_metal_color(db, MetalColorCreateRequest(base_metal_id=silver.id, name="K02 Shared Name"))
            raise AssertionError("duplicate name within the same base metal accepted")
        except HTTPException as exc:
            assert exc.status_code == 409, exc.status_code
        print("duplicate name, same base metal     OK  rejected 409")

        print("ALL OK")
    finally:
        db.close()
        outer.rollback()
        conn.close()


if __name__ == "__main__":
    main()
