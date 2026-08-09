from sqlalchemy.orm import Session
from urjaa_core.models.category import Category
from urjaa_core.models.subcategory import Subcategory


class CategoryRepository:

    @staticmethod
    def get_all_categories(db: Session):
        return (
            db.query(Category)
            .filter(Category.is_active.is_(True), Category.is_deleted.is_(False))
            .order_by(Category.display_order)
            .all()
        )

    @staticmethod
    def get_category_by_slug(db: Session, slug: str):
        return (
            db.query(Category)
            .filter(
                Category.slug == slug,
                Category.is_active.is_(True),
                Category.is_deleted.is_(False),
            )
            .first()
        )

    @staticmethod
    def get_subcategories(db: Session, category_id: int):
        return (
            db.query(Subcategory)
            .filter(Subcategory.category_id == category_id)
            .all()
        )