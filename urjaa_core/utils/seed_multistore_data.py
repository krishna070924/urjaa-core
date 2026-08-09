from __future__ import annotations

import uuid
from datetime import datetime, timezone; UTC = timezone.utc

from urjaa_core.core.user_auth import USER_SOURCE_STORE, hash_user_password
from urjaa_core.core.database import SessionLocal
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.category import Category
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.product import Product
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.sale import Sale
from urjaa_core.models.store import Store
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.user import User


def _ensure_store(name: str, location: str | None) -> Store:
    with SessionLocal() as db:
        store = db.query(Store).filter(Store.name == name).first()
        if store:
            return store

        store = Store(id=uuid.uuid4(), name=name, location=location)
        db.add(store)
        db.commit()
        db.refresh(store)
        return store


def _ensure_lookup_data() -> dict[str, str]:
    with SessionLocal() as db:
        for metal_name in ("Gold", "Silver"):
            if not db.query(BaseMetal).filter(BaseMetal.name == metal_name).first():
                db.add(BaseMetal(name=metal_name))
        for color_name in ("Yellow", "White", "Rose"):
            if not db.query(MetalColor).filter(MetalColor.name == color_name).first():
                db.add(MetalColor(name=color_name))
        db.commit()

        gold = db.query(BaseMetal).filter(BaseMetal.name == "Gold").first()
        silver = db.query(BaseMetal).filter(BaseMetal.name == "Silver").first()

        purity_targets = [
            (gold.id, "22kt", 0.916),
            (gold.id, "18kt", 0.750),
            (silver.id, "92.5", 0.925),
        ]
        for base_metal_id, label, numeric in purity_targets:
            exists = (
                db.query(MetalPurity)
                .filter(MetalPurity.base_metal_id == base_metal_id, MetalPurity.purity_label == label)
                .first()
            )
            if not exists:
                db.add(MetalPurity(base_metal_id=base_metal_id, purity_label=label, numeric_purity=numeric))
        db.commit()

        category_slug_map = {
            "rings": "Rings",
            "necklaces": "Necklaces",
            "bracelets": "Bracelets",
        }
        for slug, name in category_slug_map.items():
            if not db.query(Category).filter(Category.slug == slug).first():
                db.add(Category(name=name, slug=slug))
        db.commit()

        subcategory_targets = [
            ("rings", "Classic Rings", "classic-rings"),
            ("necklaces", "Statement Necklaces", "statement-necklaces"),
            ("bracelets", "Daily Bracelets", "daily-bracelets"),
        ]

        for category_slug, sub_name, sub_slug in subcategory_targets:
            category = db.query(Category).filter(Category.slug == category_slug).first()
            if not db.query(Subcategory).filter(Subcategory.slug == sub_slug).first():
                db.add(Subcategory(category_id=category.id, name=sub_name, slug=sub_slug))
        db.commit()

        yellow = db.query(MetalColor).filter(MetalColor.name == "Yellow").first()
        white = db.query(MetalColor).filter(MetalColor.name == "White").first()
        rose = db.query(MetalColor).filter(MetalColor.name == "Rose").first()
        gold_22 = db.query(MetalPurity).filter(MetalPurity.purity_label == "22kt").first()
        gold_18 = db.query(MetalPurity).filter(MetalPurity.purity_label == "18kt").first()
        silver_925 = db.query(MetalPurity).filter(MetalPurity.purity_label == "92.5").first()
        sub_ring = db.query(Subcategory).filter(Subcategory.slug == "classic-rings").first()
        sub_neck = db.query(Subcategory).filter(Subcategory.slug == "statement-necklaces").first()
        sub_bracelet = db.query(Subcategory).filter(Subcategory.slug == "daily-bracelets").first()

        return {
            "gold": str(gold.id),
            "silver": str(silver.id),
            "yellow": str(yellow.id),
            "white": str(white.id),
            "rose": str(rose.id),
            "gold_22": str(gold_22.id),
            "gold_18": str(gold_18.id),
            "silver_925": str(silver_925.id),
            "sub_ring": str(sub_ring.id),
            "sub_neck": str(sub_neck.id),
            "sub_bracelet": str(sub_bracelet.id),
        }


def _seed_store_data(store: Store, store_code: str, lookups: dict[str, str]) -> None:
    with SessionLocal() as db:
        templates = [
            {
                "name": "Royal Ring",
                "slug": f"royal-ring-{store_code}",
                "subcategory_id": lookups["sub_ring"],
                "variants": [
                    ("6", lookups["gold"], lookups["yellow"], lookups["gold_22"], 6.2, 24),
                    ("7", lookups["gold"], lookups["rose"], lookups["gold_18"], 5.6, 14),
                ],
            },
            {
                "name": "Royal Necklace",
                "slug": f"royal-necklace-{store_code}",
                "subcategory_id": lookups["sub_neck"],
                "variants": [
                    ("16", lookups["gold"], lookups["white"], lookups["gold_22"], 18.4, 8),
                    ("18", lookups["gold"], lookups["yellow"], lookups["gold_18"], 16.8, 5),
                ],
            },
            {
                "name": "Royal Bracelet",
                "slug": f"royal-bracelet-{store_code}",
                "subcategory_id": lookups["sub_bracelet"],
                "variants": [
                    ("S", lookups["silver"], lookups["white"], lookups["silver_925"], 10.2, 31),
                    ("M", lookups["silver"], lookups["rose"], lookups["silver_925"], 11.1, 18),
                ],
            },
        ]

        seeded_variants: list[ProductVariant] = []

        for template in templates:
            product = db.query(Product).filter(Product.slug == template["slug"]).first()
            if not product:
                product = Product(
                    id=uuid.uuid4(),
                    store_id=store.id,
                    name=template["name"],
                    slug=template["slug"],
                    description=f"{template['name']} catalog item for {store.name}",
                    subcategory_id=template["subcategory_id"],
                    status="active",
                    featured=True,
                    customizable=True,
                    is_visible_on_website=True,
                )
                db.add(product)
                db.flush()

            for index, (size, base_metal_id, metal_color_id, metal_purity_id, weight, stock) in enumerate(template["variants"], start=1):
                sku_code = f"{store_code.upper()}-{template['slug'].split('-')[1].upper()}-{index:02d}"
                variant = db.query(ProductVariant).filter(ProductVariant.sku_code == sku_code).first()
                if not variant:
                    variant = ProductVariant(
                        id=uuid.uuid4(),
                        store_id=store.id,
                        product_id=product.id,
                        size=size,
                        base_metal_id=base_metal_id,
                        metal_color_id=metal_color_id,
                        metal_purity_id=metal_purity_id,
                        metal_weight_grams=weight,
                        stone_quantity=0,
                        stone_cost=0,
                        making_charges=3000,
                        price_override=None,
                        stock_quantity=stock,
                        sku_code=sku_code,
                        status="active",
                    )
                    db.add(variant)
                seeded_variants.append(variant)

        customer_names = [
            f"{store.name} Customer 1",
            f"{store.name} Customer 2",
            f"{store.name} Customer 3",
            f"{store.name} Customer 4",
        ]
        customers: list[User] = []
        for idx, name in enumerate(customer_names, start=1):
            email = f"customer{idx}.{store_code}@urjaa.example".lower()
            customer = db.query(User).filter(User.email == email).first()
            if not customer:
                customer = User(
                    email=email,
                    password_hash=hash_user_password(uuid.uuid4().hex),
                    full_name=name,
                    phone=f"9998800{idx:03d}",
                    source=USER_SOURCE_STORE,
                    address=f"{store.location or 'Unknown'}",
                    provider="local",
                    provider_id=None,
                    is_active=True,
                )
                db.add(customer)
                db.flush()
            else:
                customer.full_name = customer.full_name or name
                customer.phone = customer.phone or f"9998800{idx:03d}"
                customer.source = customer.source or USER_SOURCE_STORE
                customer.address = customer.address or f"{store.location or 'Unknown'}"
            customers.append(customer)

        db.flush()

        sales_target = 6
        existing_sales = db.query(Sale).filter(Sale.store_id == store.id).count()
        sales_to_create = max(0, sales_target - existing_sales)

        for i in range(sales_to_create):
            variant = seeded_variants[i % len(seeded_variants)]
            if variant.stock_quantity <= 1:
                continue
            customer = customers[i % len(customers)]
            quantity = 1
            variant.stock_quantity -= quantity
            final_price = float((variant.metal_weight_grams or 0) * 7000 + (variant.making_charges or 0))
            cost_price = round(final_price * 0.82, 2)
            profit = round(final_price - cost_price, 2)
            db.add(
                Sale(
                    id=uuid.uuid4(),
                    store_id=store.id,
                    product_id=variant.product_id,
                    variant_id=variant.id,
                    customer_id=customer.id,
                    quantity=quantity,
                    final_price=final_price,
                    cost_price=cost_price,
                    profit=profit,
                    source="store",
                    date_time=datetime.now(UTC),
                )
            )

        db.commit()


def main() -> None:
    lookups = _ensure_lookup_data()

    urjaa_1 = _ensure_store("Urjaa 1", "Vaishali Nagar")
    urjaa_2 = _ensure_store("Urjaa 2", "Malviya Nagar")

    _seed_store_data(urjaa_1, "urjaa1", lookups)
    _seed_store_data(urjaa_2, "urjaa2", lookups)

    print("Seeded multi-store data successfully for Urjaa 1 and Urjaa 2")


if __name__ == "__main__":
    main()
