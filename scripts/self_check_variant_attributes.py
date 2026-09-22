"""Self-check for the variant-attribute-system schema (task 01).

Round-trips one VariantType + Attribute + AttributeValue, links them via
variant_type_attributes, creates one ProductVariant, links it to the
AttributeValue via variant_attributes, and asserts everything reads back
correctly through the ORM relationships. Not wired into `pytest tests/`
(CI runs pytest before `alembic upgrade head`, so a DB-backed test would
fail on a fresh CI DB) — run manually against a migrated DB:

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/urjaa \
        python scripts/self_check_variant_attributes.py

All rows are created and deleted inside one transaction that's always
rolled back, so this is safe to run against a real dev DB.
"""

import os
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import urjaa_core.models  # noqa: F401  (register all models on Base metadata)
from urjaa_core.models.attribute import Attribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.variant_attribute import VariantAttribute
from urjaa_core.models.variant_type import VariantType
from urjaa_core.models.variant_type_attribute import VariantTypeAttribute


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        store_id = session.execute(
            text("SELECT id FROM stores LIMIT 1")
        ).scalar()
        assert store_id is not None, "self-check needs at least one existing store row"

        variant_type = VariantType(name="Ring", slug=f"ring-{uuid.uuid4().hex[:8]}")
        attribute = Attribute(name="Ring Size", slug=f"ring-size-{uuid.uuid4().hex[:8]}")
        session.add_all([variant_type, attribute])
        session.flush()

        attribute_value = AttributeValue(attribute_id=attribute.id, value="6")
        session.add(attribute_value)
        session.flush()

        vt_attr = VariantTypeAttribute(variant_type_id=variant_type.id, attribute_id=attribute.id)
        session.add(vt_attr)

        variant = ProductVariant(store_id=store_id, sku_code=f"SELFCHECK-{uuid.uuid4().hex[:8]}")
        session.add(variant)
        session.flush()

        variant_attr = VariantAttribute(variant_id=variant.id, attribute_value_id=attribute_value.id)
        session.add(variant_attr)
        session.flush()

        # Round trip: variant_type -> attributes -> variant_type_attributes
        session.refresh(variant_type)
        assert len(variant_type.attributes) == 1
        assert variant_type.attributes[0].attribute.name == "Ring Size"

        # Round trip: variant -> attribute_values -> variant_attributes
        session.refresh(variant)
        assert len(variant.attribute_values) == 1
        linked_value = variant.attribute_values[0].attribute_value
        assert linked_value.value == "6"
        assert linked_value.attribute.name == "Ring Size"

        # Round trip: attribute_value -> variant_attributes back-ref
        session.refresh(attribute_value)
        assert len(attribute_value.variant_attributes) == 1
        assert attribute_value.variant_attributes[0].variant_id == variant.id

        # Uniqueness constraint: duplicate (variant_id, attribute_value_id) must fail
        from sqlalchemy.exc import IntegrityError

        session.add(VariantAttribute(variant_id=variant.id, attribute_value_id=attribute_value.id))
        try:
            session.flush()
            raise AssertionError("expected IntegrityError on duplicate variant_attributes row")
        except IntegrityError:
            session.rollback()

        print("OK: variant attribute round trip + uniqueness constraint verified")
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
