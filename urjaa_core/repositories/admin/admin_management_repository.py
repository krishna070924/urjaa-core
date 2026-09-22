from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, selectinload

from urjaa_core.models.attribute import Attribute
from urjaa_core.models.attribute_value import AttributeValue
from urjaa_core.models.base_metal import BaseMetal
from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.metal_color import MetalColor
from urjaa_core.models.metal_purity import MetalPurity
from urjaa_core.models.metal_rate import MetalRate
from urjaa_core.models.product import Product
from urjaa_core.models.product_attribute import ProductAttribute
from urjaa_core.models.product_collection import ProductCollection
from urjaa_core.models.product_image import ProductImage
from urjaa_core.models.product_stone import ProductStone
from urjaa_core.models.product_tag import ProductTag
from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.stone import Stone
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag
from urjaa_core.models.variant_type import VariantType
from urjaa_core.models.variant_type_attribute import VariantTypeAttribute
from urjaa_core.models.variant_attribute import VariantAttribute
from urjaa_core.models.sale import Sale


class AdminManagementRepository:
    @staticmethod
    def count_products(db: Session, store_id: UUID) -> int:
        return int(db.query(func.count(Product.id)).filter(Product.store_id == store_id).scalar() or 0)

    @staticmethod
    def count_products_by_status(db: Session, status: str, store_id: UUID) -> int:
        return int(
            db.query(func.count(Product.id))
            .filter(Product.status == status, Product.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def count_variants(db: Session, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id)).filter(ProductVariant.store_id == store_id).scalar() or 0
        )

    @staticmethod
    def count_collections(db: Session) -> int:
        return int(db.query(func.count(Collection.id)).scalar() or 0)

    @staticmethod
    def count_low_stock_variants(db: Session, threshold: int, store_id: UUID) -> int:
        return int(
            db.query(func.count(ProductVariant.id))
            .filter(ProductVariant.stock_quantity <= threshold, ProductVariant.store_id == store_id)
            .scalar()
            or 0
        )

    @staticmethod
    def get_recent_products(db: Session, store_id: UUID, limit: int = 5) -> list[Product]:
        return (
            db.query(Product)
            .options(selectinload(Product.variants))
            .filter(Product.store_id == store_id)
            .order_by(Product.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_low_stock_variants(
        db: Session,
        threshold: int,
        store_id: UUID,
        limit: int = 10,
    ) -> list[tuple[ProductVariant, Product]]:
        return (
            db.query(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(ProductVariant.stock_quantity <= threshold, ProductVariant.store_id == store_id)
            .order_by(ProductVariant.stock_quantity.asc(), Product.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_latest_metal_rate_by_name(db: Session, metal_name: str) -> MetalRate | None:
        return (
            db.query(MetalRate)
            .join(BaseMetal, BaseMetal.id == MetalRate.base_metal_id)
            .options(selectinload(MetalRate.base_metal))
            .filter(func.lower(BaseMetal.name) == metal_name.lower())
            .order_by(MetalRate.effective_from.desc(), MetalRate.id.desc())
            .first()
        )

    @staticmethod
    def get_recent_metal_rates_by_name(db: Session, metal_name: str, limit: int = 2) -> list[MetalRate]:
        return (
            db.query(MetalRate)
            .join(BaseMetal, BaseMetal.id == MetalRate.base_metal_id)
            .filter(func.lower(BaseMetal.name) == metal_name.lower())
            .order_by(MetalRate.effective_from.desc(), MetalRate.id.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_variant_pricing_snapshot(db: Session, store_id: UUID) -> tuple[float | None, float | None, float | None]:
        latest_rate_subquery = (
            db.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                func.max(MetalRate.effective_from).label("latest_effective_from"),
            )
            .group_by(MetalRate.base_metal_id)
            .subquery()
        )

        latest_rates = (
            db.query(
                MetalRate.base_metal_id.label("base_metal_id"),
                MetalRate.rate_per_gram.label("rate_per_gram"),
            )
            .join(
                latest_rate_subquery,
                (MetalRate.base_metal_id == latest_rate_subquery.c.base_metal_id)
                & (MetalRate.effective_from == latest_rate_subquery.c.latest_effective_from),
            )
            .subquery()
        )

        purity_factor = func.coalesce(MetalPurity.numeric_purity / 100, 1)

        computed_price = func.coalesce(
            ProductVariant.price_override,
            (func.coalesce(ProductVariant.metal_weight_grams, 0) * func.coalesce(latest_rates.c.rate_per_gram, 0) * purity_factor)
            + func.coalesce(ProductVariant.stone_cost, 0)
            + func.coalesce(ProductVariant.making_charges, 0),
        )

        row = (
            db.query(
                func.avg(computed_price).label("avg_price"),
                func.max(computed_price).label("max_price"),
                func.min(computed_price).label("min_price"),
            )
            .outerjoin(latest_rates, latest_rates.c.base_metal_id == ProductVariant.base_metal_id)
            .outerjoin(MetalPurity, MetalPurity.id == ProductVariant.metal_purity_id)
            .filter(ProductVariant.store_id == store_id)
            .first()
        )

        if not row:
            return None, None, None

        avg_price = float(row.avg_price) if row.avg_price is not None else None
        max_price = float(row.max_price) if row.max_price is not None else None
        min_price = float(row.min_price) if row.min_price is not None else None
        return avg_price, max_price, min_price

    @staticmethod
    def get_sales_insights(db: Session, store_id: UUID, top_limit: int = 5) -> dict:
        profit_expr = func.coalesce(
            Sale.profit,
            Sale.final_price - func.coalesce(Sale.cost_price, 0),
            0,
        )

        totals = (
            db.query(
                func.coalesce(func.sum(Sale.final_price), 0).label("total_revenue"),
                func.coalesce(
                    func.sum(case((Sale.source == "store", Sale.final_price), else_=0)),
                    0,
                ).label("store_revenue"),
                func.coalesce(
                    func.sum(case((Sale.source == "website", Sale.final_price), else_=0)),
                    0,
                ).label("website_revenue"),
                func.coalesce(func.sum(profit_expr), 0).label("total_profit"),
                func.count(Sale.id).label("total_sales_count"),
            )
            .filter(Sale.store_id == store_id)
            .first()
        )

        top_rows = (
            db.query(
                Sale.product_id.label("product_id"),
                Product.name.label("product_name"),
                func.coalesce(func.sum(Sale.quantity), 0).label("units_sold"),
                func.coalesce(func.sum(Sale.final_price), 0).label("revenue"),
                func.count(Sale.id).label("sales_count"),
            )
            .join(Product, Product.id == Sale.product_id)
            .filter(Sale.store_id == store_id)
            .group_by(Sale.product_id, Product.name)
            .order_by(
                func.coalesce(func.sum(Sale.quantity), 0).desc(),
                func.coalesce(func.sum(Sale.final_price), 0).desc(),
            )
            .limit(top_limit)
            .all()
        )

        total_revenue = float(totals.total_revenue) if totals and totals.total_revenue is not None else 0.0
        total_profit = float(totals.total_profit) if totals and totals.total_profit is not None else 0.0
        profit_margin = (total_profit / total_revenue) if total_revenue > 0 else 0.0

        return {
            "total_revenue": total_revenue,
            "store_revenue": float(totals.store_revenue) if totals and totals.store_revenue is not None else 0.0,
            "website_revenue": float(totals.website_revenue) if totals and totals.website_revenue is not None else 0.0,
            "total_profit": total_profit,
            "profit_margin": profit_margin,
            "total_sales_count": int(totals.total_sales_count) if totals and totals.total_sales_count is not None else 0,
            "top_selling_products": [
                {
                    "product_id": row.product_id,
                    "product_name": row.product_name,
                    "units_sold": int(row.units_sold or 0),
                    "revenue": float(row.revenue or 0),
                    "sales_count": int(row.sales_count or 0),
                }
                for row in top_rows
            ],
        }

    @staticmethod
    def get_daily_revenue_trend(db: Session, store_id: UUID, days: int = 30) -> list[dict]:
        if days <= 0:
            return []

        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)

        rows = (
            db.query(
                func.date(Sale.date_time).label("date"),
                func.coalesce(
                    func.sum(case((Sale.source == "store", Sale.final_price), else_=0)),
                    0,
                ).label("store"),
                func.coalesce(
                    func.sum(case((Sale.source == "website", Sale.final_price), else_=0)),
                    0,
                ).label("website"),
                func.coalesce(
                    func.sum(
                        func.coalesce(
                            Sale.profit,
                            Sale.final_price - func.coalesce(Sale.cost_price, 0),
                            0,
                        )
                    ),
                    0,
                ).label("profit"),
            )
            .filter(
                Sale.store_id == store_id,
                func.date(Sale.date_time) >= start_date,
                func.date(Sale.date_time) <= end_date,
            )
            .group_by(func.date(Sale.date_time))
            .order_by(func.date(Sale.date_time).asc())
            .all()
        )

        revenue_by_date: dict[date, dict[str, float]] = {}
        for row in rows:
            row_date = row.date if isinstance(row.date, date) else date.fromisoformat(str(row.date))
            revenue_by_date[row_date] = {
                "store": float(row.store or 0),
                "website": float(row.website or 0),
                "profit": float(row.profit or 0),
            }

        daily_revenue: list[dict] = []
        for offset in range(days):
            current_date = start_date + timedelta(days=offset)
            values = revenue_by_date.get(current_date, {"store": 0.0, "website": 0.0, "profit": 0.0})
            daily_revenue.append(
                {
                    "date": current_date,
                    "store": values["store"],
                    "website": values["website"],
                    "profit": values["profit"],
                }
            )

        return daily_revenue

    @staticmethod
    def get_metal_purity_by_metal_and_label(db: Session, metal_name: str, label_contains: str) -> MetalPurity | None:
        return (
            db.query(MetalPurity)
            .join(BaseMetal, BaseMetal.id == MetalPurity.base_metal_id)
            .filter(
                func.lower(BaseMetal.name) == metal_name.lower(),
                func.lower(MetalPurity.purity_label).contains(label_contains.lower()),
            )
            .order_by(MetalPurity.numeric_purity.desc())
            .first()
        )

    @staticmethod
    def get_categories(db: Session, include_inactive: bool = False) -> list[Category]:
        query = db.query(Category)
        if not include_inactive:
            query = query.filter(Category.is_active.is_(True), Category.is_deleted.is_(False))
        return query.order_by(Category.display_order.asc().nullslast(), Category.name.asc()).all()

    @staticmethod
    def get_subcategories(db: Session) -> list[Subcategory]:
        return (
            db.query(Subcategory)
            .join(Category, Category.id == Subcategory.category_id)
            .filter(Category.is_active.is_(True), Category.is_deleted.is_(False))
            .order_by(Subcategory.name.asc())
            .all()
        )

    @staticmethod
    def get_subcategory_by_slug(db: Session, slug: str) -> Subcategory | None:
        return (
            db.query(Subcategory)
            .join(Category, Category.id == Subcategory.category_id)
            .filter(
                Subcategory.slug == slug,
                Category.is_active.is_(True),
                Category.is_deleted.is_(False),
            )
            .first()
        )

    @staticmethod
    def get_subcategory_by_name(db: Session, name: str, category_id: int | None = None) -> Subcategory | None:
        query = (
            db.query(Subcategory)
            .join(Category, Category.id == Subcategory.category_id)
            .filter(
                func.lower(Subcategory.name) == name.strip().lower(),
                Category.is_active.is_(True),
                Category.is_deleted.is_(False),
            )
        )
        if category_id is not None:
            query = query.filter(Subcategory.category_id == category_id)
        return query.first()

    @staticmethod
    def create_subcategory(db: Session, subcategory: Subcategory) -> Subcategory:
        db.add(subcategory)
        db.flush()
        db.refresh(subcategory)
        return subcategory

    @staticmethod
    def delete_subcategory(db: Session, subcategory: Subcategory) -> None:
        db.delete(subcategory)

    @staticmethod
    def get_variant_types(db: Session) -> list[VariantType]:
        return (
            db.query(VariantType)
            .options(selectinload(VariantType.attributes))
            .order_by(VariantType.display_order.asc().nullslast(), VariantType.name.asc())
            .all()
        )

    @staticmethod
    def get_variant_type_by_id(db: Session, variant_type_id: int) -> VariantType | None:
        return (
            db.query(VariantType)
            .options(
                selectinload(VariantType.attributes)
                .selectinload(VariantTypeAttribute.attribute)
                .selectinload(Attribute.values)
            )
            .filter(VariantType.id == variant_type_id)
            .first()
        )

    @staticmethod
    def get_variant_type_by_slug(db: Session, slug: str) -> VariantType | None:
        return db.query(VariantType).filter(VariantType.slug == slug).first()

    @staticmethod
    def create_variant_type(db: Session, variant_type: VariantType) -> VariantType:
        db.add(variant_type)
        db.flush()
        db.refresh(variant_type)
        return variant_type

    @staticmethod
    def update_variant_type(db: Session, variant_type: VariantType) -> VariantType:
        db.flush()
        db.refresh(variant_type)
        return variant_type

    @staticmethod
    def delete_variant_type(db: Session, variant_type: VariantType) -> None:
        db.delete(variant_type)

    @staticmethod
    def replace_variant_type_attributes(db: Session, variant_type_id: int, attribute_ids: list[int]) -> None:
        db.query(VariantTypeAttribute).filter(VariantTypeAttribute.variant_type_id == variant_type_id).delete()
        for attribute_id in attribute_ids:
            db.add(VariantTypeAttribute(variant_type_id=variant_type_id, attribute_id=attribute_id))

    @staticmethod
    def get_collections(db: Session) -> list[Collection]:
        return db.query(Collection).order_by(Collection.display_order.asc().nullslast(), Collection.name.asc()).all()

    @staticmethod
    def get_tags(db: Session) -> list[Tag]:
        return db.query(Tag).order_by(Tag.name.asc()).all()

    @staticmethod
    def get_stones(db: Session) -> list[Stone]:
        return db.query(Stone).order_by(Stone.name.asc()).all()

    @staticmethod
    def get_attributes(db: Session) -> list[Attribute]:
        return (
            db.query(Attribute)
            .options(selectinload(Attribute.values))
            .order_by(Attribute.name.asc())
            .all()
        )

    @staticmethod
    def get_metal_purities(db: Session) -> list[MetalPurity]:
        return (
            db.query(MetalPurity)
            .options(selectinload(MetalPurity.base_metal))
            .order_by(MetalPurity.base_metal_id.asc(), MetalPurity.numeric_purity.desc())
            .all()
        )

    @staticmethod
    def get_metal_types(db: Session) -> list[BaseMetal]:
        return db.query(BaseMetal).order_by(BaseMetal.name.asc()).all()

    @staticmethod
    def get_metal_type_by_id(db: Session, metal_type_id: int) -> BaseMetal | None:
        return db.query(BaseMetal).filter(BaseMetal.id == metal_type_id).first()

    @staticmethod
    def get_metal_type_by_name(db: Session, name: str) -> BaseMetal | None:
        return db.query(BaseMetal).filter(func.lower(BaseMetal.name) == name.lower()).first()

    @staticmethod
    def create_metal_type(db: Session, metal_type: BaseMetal) -> BaseMetal:
        db.add(metal_type)
        db.flush()
        db.refresh(metal_type)
        return metal_type

    @staticmethod
    def update_metal_type(db: Session, metal_type: BaseMetal) -> BaseMetal:
        db.flush()
        db.refresh(metal_type)
        return metal_type

    @staticmethod
    def delete_metal_type(db: Session, metal_type: BaseMetal) -> None:
        db.delete(metal_type)

    @staticmethod
    def get_metal_purity_by_id(db: Session, metal_purity_id: int) -> MetalPurity | None:
        return (
            db.query(MetalPurity)
            .options(selectinload(MetalPurity.base_metal))
            .filter(MetalPurity.id == metal_purity_id)
            .first()
        )

    @staticmethod
    def get_metal_purity_by_values(db: Session, base_metal_id: int, purity_label: str) -> MetalPurity | None:
        return (
            db.query(MetalPurity)
            .filter(
                MetalPurity.base_metal_id == base_metal_id,
                func.lower(MetalPurity.purity_label) == purity_label.lower(),
            )
            .first()
        )

    @staticmethod
    def create_metal_purity(db: Session, metal_purity: MetalPurity) -> MetalPurity:
        db.add(metal_purity)
        db.flush()
        db.refresh(metal_purity)
        return metal_purity

    @staticmethod
    def delete_metal_purity(db: Session, metal_purity: MetalPurity) -> None:
        db.delete(metal_purity)

    @staticmethod
    def get_metal_colors(db: Session) -> list[MetalColor]:
        return db.query(MetalColor).order_by(MetalColor.name.asc()).all()

    @staticmethod
    def get_metal_color_by_id(db: Session, metal_color_id: int) -> MetalColor | None:
        return db.query(MetalColor).filter(MetalColor.id == metal_color_id).first()

    @staticmethod
    def get_metal_color_by_name(db: Session, name: str) -> MetalColor | None:
        return db.query(MetalColor).filter(func.lower(MetalColor.name) == name.lower()).first()

    @staticmethod
    def create_metal_color(db: Session, metal_color: MetalColor) -> MetalColor:
        db.add(metal_color)
        db.flush()
        db.refresh(metal_color)
        return metal_color

    @staticmethod
    def update_metal_color(db: Session, metal_color: MetalColor) -> MetalColor:
        db.flush()
        db.refresh(metal_color)
        return metal_color

    @staticmethod
    def delete_metal_color(db: Session, metal_color: MetalColor) -> None:
        db.delete(metal_color)

    @staticmethod
    def get_metal_rates(db: Session) -> list[MetalRate]:
        return (
            db.query(MetalRate)
            .options(selectinload(MetalRate.base_metal))
            .order_by(MetalRate.effective_from.desc(), MetalRate.id.desc())
            .all()
        )

    @staticmethod
    def get_category_by_id(db: Session, category_id: int) -> Category | None:
        return (
            db.query(Category)
            .filter(Category.id == category_id, Category.is_active.is_(True), Category.is_deleted.is_(False))
            .first()
        )

    @staticmethod
    def get_category_by_slug(db: Session, slug: str, include_inactive: bool = False) -> Category | None:
        query = db.query(Category).filter(Category.slug == slug)
        if not include_inactive:
            query = query.filter(Category.is_active.is_(True), Category.is_deleted.is_(False))
        return query.first()

    @staticmethod
    def get_category_by_name(db: Session, name: str) -> Category | None:
        return (
            db.query(Category)
            .filter(
                func.lower(Category.name) == name.strip().lower(),
                Category.is_active.is_(True),
                Category.is_deleted.is_(False),
            )
            .first()
        )

    @staticmethod
    def get_category_by_id_with_inactive(db: Session, category_id: int) -> Category | None:
        return db.query(Category).filter(Category.id == category_id).first()

    @staticmethod
    def count_products_linked_to_category(db: Session, category_id: int) -> int:
        return int(
            db.query(func.count(Product.id))
            .join(Subcategory, Subcategory.id == Product.subcategory_id)
            .filter(Subcategory.category_id == category_id)
            .scalar()
            or 0
        )

    @staticmethod
    def delete_subcategories_by_category(db: Session, category_id: int) -> int:
        return (
            db.query(Subcategory)
            .filter(Subcategory.category_id == category_id)
            .delete(synchronize_session=False)
        )

    @staticmethod
    def create_category(db: Session, category: Category) -> Category:
        db.add(category)
        db.flush()
        db.refresh(category)
        return category

    @staticmethod
    def delete_category(db: Session, category: Category) -> None:
        db.delete(category)

    @staticmethod
    def get_collection_by_id(db: Session, collection_id: int) -> Collection | None:
        return db.query(Collection).filter(Collection.id == collection_id).first()

    @staticmethod
    def get_collection_by_slug(db: Session, slug: str) -> Collection | None:
        return db.query(Collection).filter(Collection.slug == slug).first()

    @staticmethod
    def create_collection(db: Session, collection: Collection) -> Collection:
        db.add(collection)
        db.flush()
        db.refresh(collection)
        return collection

    @staticmethod
    def delete_collection(db: Session, collection: Collection) -> None:
        db.delete(collection)

    @staticmethod
    def get_tag_by_id(db: Session, tag_id: int) -> Tag | None:
        return db.query(Tag).filter(Tag.id == tag_id).first()

    @staticmethod
    def get_tag_by_slug(db: Session, slug: str) -> Tag | None:
        return db.query(Tag).filter(Tag.slug == slug).first()

    @staticmethod
    def create_tag(db: Session, tag: Tag) -> Tag:
        db.add(tag)
        db.flush()
        db.refresh(tag)
        return tag

    @staticmethod
    def delete_tag(db: Session, tag: Tag) -> None:
        db.delete(tag)

    @staticmethod
    def get_stone_by_id(db: Session, stone_id: int) -> Stone | None:
        return db.query(Stone).filter(Stone.id == stone_id).first()

    @staticmethod
    def get_stone_by_name(db: Session, name: str) -> Stone | None:
        return db.query(Stone).filter(func.lower(Stone.name) == name.lower()).first()

    @staticmethod
    def create_stone(db: Session, stone: Stone) -> Stone:
        db.add(stone)
        db.flush()
        db.refresh(stone)
        return stone

    @staticmethod
    def delete_stone(db: Session, stone: Stone) -> None:
        db.delete(stone)

    @staticmethod
    def get_attribute_by_id(db: Session, attribute_id: int) -> Attribute | None:
        return (
            db.query(Attribute)
            .options(selectinload(Attribute.values))
            .filter(Attribute.id == attribute_id)
            .first()
        )

    @staticmethod
    def get_attribute_by_slug(db: Session, slug: str) -> Attribute | None:
        return db.query(Attribute).filter(Attribute.slug == slug).first()

    @staticmethod
    def create_attribute(db: Session, attribute: Attribute) -> Attribute:
        db.add(attribute)
        db.flush()
        db.refresh(attribute)
        return attribute

    @staticmethod
    def delete_attribute(db: Session, attribute: Attribute) -> None:
        db.delete(attribute)

    @staticmethod
    def get_attribute_values(db: Session) -> list[AttributeValue]:
        return (
            db.query(AttributeValue)
            .options(selectinload(AttributeValue.attribute))
            .order_by(AttributeValue.id.asc())
            .all()
        )

    @staticmethod
    def get_attribute_value_by_id(db: Session, value_id: int) -> AttributeValue | None:
        return (
            db.query(AttributeValue)
            .options(selectinload(AttributeValue.attribute))
            .filter(AttributeValue.id == value_id)
            .first()
        )

    @staticmethod
    def get_attribute_value_by_attribute_and_value(
        db: Session,
        attribute_id: int,
        value: str,
    ) -> AttributeValue | None:
        return (
            db.query(AttributeValue)
            .filter(AttributeValue.attribute_id == attribute_id, func.lower(AttributeValue.value) == value.lower())
            .first()
        )

    @staticmethod
    def create_attribute_value(db: Session, value: AttributeValue) -> AttributeValue:
        db.add(value)
        db.flush()
        db.refresh(value)
        return value

    @staticmethod
    def delete_attribute_value(db: Session, value: AttributeValue) -> None:
        db.delete(value)

    @staticmethod
    def get_metal_rate_by_id(db: Session, rate_id: int) -> MetalRate | None:
        return (
            db.query(MetalRate)
            .options(selectinload(MetalRate.base_metal))
            .filter(MetalRate.id == rate_id)
            .first()
        )

    @staticmethod
    def get_products_page(
        db: Session,
        page: int,
        limit: int,
        store_id: UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[Product], int]:
        offset = (page - 1) * limit
        query = (
            db.query(Product)
            .options(selectinload(Product.subcategory), selectinload(Product.variants), selectinload(Product.store))
            .outerjoin(Subcategory, Subcategory.id == Product.subcategory_id)
            .outerjoin(Category, Category.id == Subcategory.category_id)
            .order_by(Product.created_at.desc())
        )

        if store_id is not None:
            query = query.filter(Product.store_id == store_id)

        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(Product.name).like(pattern),
                    func.lower(Product.description).like(pattern),
                    func.lower(Category.name).like(pattern),
                )
            )

        total = query.count()
        items = query.offset(offset).limit(limit).all()
        return items, total

    @staticmethod
    def get_all_products_with_relations(db: Session) -> list[Product]:
        return (
            db.query(Product)
            .options(
                selectinload(Product.subcategory),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
            .order_by(Product.updated_at.desc().nullslast(), Product.created_at.desc().nullslast())
            .all()
        )

    @staticmethod
    def get_product_by_id(db: Session, product_id: UUID, store_id: UUID) -> Product | None:
        return (
            db.query(Product)
            .options(selectinload(Product.subcategory))
            .filter(Product.id == product_id, Product.store_id == store_id)
            .first()
        )

    @staticmethod
    def get_product_with_relations(db: Session, product_id: UUID, store_id: UUID) -> Product | None:
        return (
            db.query(Product)
            .options(
                selectinload(Product.subcategory),
                selectinload(Product.variants),
                selectinload(Product.images),
                selectinload(Product.collections),
                selectinload(Product.tags),
                selectinload(Product.attributes).selectinload(ProductAttribute.attribute_value),
                selectinload(Product.stones),
            )
            .filter(Product.id == product_id, Product.store_id == store_id)
            .first()
        )

    @staticmethod
    def get_product_by_slug(db: Session, slug: str, store_id: UUID) -> Product | None:
        return db.query(Product).filter(Product.slug == slug, Product.store_id == store_id).first()

    @staticmethod
    def get_product_by_slug_global(db: Session, slug: str) -> Product | None:
        """Check slug existence across all stores (matches the global unique DB constraint)."""
        return db.query(Product).filter(Product.slug == slug).first()

    @staticmethod
    def create_product(db: Session, product: Product) -> Product:
        db.add(product)
        db.flush()
        db.refresh(product)
        return product

    @staticmethod
    def delete_product_dependencies(db: Session, product_id: UUID, store_id: UUID) -> None:
        db.query(ProductImage).filter(ProductImage.product_id == product_id).delete()
        db.query(ProductVariant).filter(ProductVariant.product_id == product_id, ProductVariant.store_id == store_id).delete()
        db.query(ProductStone).filter(ProductStone.product_id == product_id).delete()
        db.query(ProductAttribute).filter(ProductAttribute.product_id == product_id).delete()
        db.query(ProductCollection).filter(ProductCollection.product_id == product_id).delete()
        db.query(ProductTag).filter(ProductTag.product_id == product_id).delete()

    @staticmethod
    def delete_product(db: Session, product: Product) -> None:
        db.delete(product)

    @staticmethod
    def get_subcategory_by_id(db: Session, subcategory_id: int) -> Subcategory | None:
        return (
            db.query(Subcategory)
            .options(selectinload(Subcategory.category))
            .filter(Subcategory.id == subcategory_id)
            .first()
        )

    @staticmethod
    def get_variant_by_id(db: Session, variant_id: UUID, store_id: UUID) -> ProductVariant | None:
        return (
            db.query(ProductVariant)
            .filter(ProductVariant.id == variant_id, ProductVariant.store_id == store_id)
            .first()
        )

    @staticmethod
    def get_variant_by_sku(db: Session, sku_code: str, store_id: UUID) -> ProductVariant | None:
        return (
            db.query(ProductVariant)
            .filter(ProductVariant.sku_code == sku_code, ProductVariant.store_id == store_id)
            .first()
        )

    @staticmethod
    def create_variant(db: Session, variant: ProductVariant) -> ProductVariant:
        db.add(variant)
        db.flush()
        db.refresh(variant)
        return variant

    @staticmethod
    def delete_variant(db: Session, variant: ProductVariant) -> None:
        db.delete(variant)

    @staticmethod
    def get_image_by_id(db: Session, image_id: int) -> ProductImage | None:
        return db.query(ProductImage).filter(ProductImage.id == image_id).first()

    @staticmethod
    def get_product_images(db: Session, product_id: UUID) -> list[ProductImage]:
        return (
            db.query(ProductImage)
            .filter(ProductImage.product_id == product_id)
            .order_by(ProductImage.display_order.asc().nullslast(), ProductImage.id.asc())
            .all()
        )

    @staticmethod
    def get_max_image_order(db: Session, product_id: UUID) -> int:
        max_order = (
            db.query(func.max(ProductImage.display_order))
            .filter(ProductImage.product_id == product_id)
            .scalar()
        )
        return int(max_order or 0)

    @staticmethod
    def unset_primary_images(db: Session, product_id: UUID) -> None:
        (
            db.query(ProductImage)
            .filter(ProductImage.product_id == product_id)
            .update({ProductImage.is_primary: False}, synchronize_session=False)
        )

    @staticmethod
    def create_image(db: Session, image: ProductImage) -> ProductImage:
        db.add(image)
        db.flush()
        db.refresh(image)
        return image

    @staticmethod
    def delete_image(db: Session, image: ProductImage) -> None:
        db.delete(image)

    @staticmethod
    def get_collections_by_ids(db: Session, ids: list[int]) -> list[Collection]:
        if not ids:
            return []
        return db.query(Collection).filter(Collection.id.in_(ids)).all()

    @staticmethod
    def get_tags_by_ids(db: Session, ids: list[int]) -> list[Tag]:
        if not ids:
            return []
        return db.query(Tag).filter(Tag.id.in_(ids)).all()

    @staticmethod
    def get_attribute_values_by_ids(db: Session, ids: list[int]) -> list[AttributeValue]:
        if not ids:
            return []
        return db.query(AttributeValue).filter(AttributeValue.id.in_(ids)).all()

    @staticmethod
    def get_attributes_by_ids(db: Session, ids: list[int]) -> list[Attribute]:
        if not ids:
            return []
        return db.query(Attribute).filter(Attribute.id.in_(ids)).all()

    @staticmethod
    def get_stones_by_ids(db: Session, ids: list[int]) -> list[Stone]:
        if not ids:
            return []
        return db.query(Stone).filter(Stone.id.in_(ids)).all()

    @staticmethod
    def replace_product_attributes(db: Session, product_id: UUID, attribute_value_ids: list[int]) -> None:
        db.query(ProductAttribute).filter(ProductAttribute.product_id == product_id).delete()
        for value_id in attribute_value_ids:
            db.add(ProductAttribute(product_id=product_id, attribute_value_id=value_id))

    @staticmethod
    def replace_variant_attributes(db: Session, variant_id: UUID, attribute_value_ids: list[int]) -> None:
        db.query(VariantAttribute).filter(VariantAttribute.variant_id == variant_id).delete()
        for value_id in attribute_value_ids:
            db.add(VariantAttribute(variant_id=variant_id, attribute_value_id=value_id))

    @staticmethod
    def replace_product_stones(
        db: Session,
        product_id: UUID,
        stones: list[dict],
    ) -> None:
        db.query(ProductStone).filter(ProductStone.product_id == product_id).delete()
        for stone in stones:
            db.add(
                ProductStone(
                    product_id=product_id,
                    stone_id=stone["stone_id"],
                    quantity=stone.get("quantity"),
                    total_carat_weight=stone.get("total_carat_weight"),
                )
            )
