from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.category import Category
from urjaa_core.models.collection import Collection
from urjaa_core.models.product import Product
from urjaa_core.models.subcategory import Subcategory
from urjaa_core.models.tag import Tag


class WebsiteRepository:
    @staticmethod
    def count_categories(db: Session) -> int:
        return int(db.query(func.count(Category.id)).scalar() or 0)

    @staticmethod
    def count_subcategories(db: Session) -> int:
        return int(db.query(func.count(Subcategory.id)).scalar() or 0)

    @staticmethod
    def count_collections(db: Session) -> int:
        return int(db.query(func.count(Collection.id)).scalar() or 0)

    @staticmethod
    def count_featured_collections(db: Session) -> int:
        return int(db.query(func.count(Collection.id)).filter(Collection.is_featured.is_(True)).scalar() or 0)

    @staticmethod
    def count_tags(db: Session) -> int:
        return int(db.query(func.count(Tag.id)).scalar() or 0)

    @staticmethod
    def count_recent_product_updates(db: Session, store_id: UUID, last_days: int = 7) -> int:
        cutoff = datetime.utcnow() - timedelta(days=last_days)
        return int(
            db.query(func.count(Product.id))
            .filter(Product.updated_at >= cutoff, Product.store_id == store_id)
            .scalar()
            or 0
        )
