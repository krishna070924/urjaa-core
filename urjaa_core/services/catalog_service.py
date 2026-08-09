from sqlalchemy.orm import Session

from urjaa_core.repositories.category_repository import CategoryRepository


class CatalogService:

    @staticmethod
    def get_categories(db: Session):
        return CategoryRepository.get_all_categories(db)

    @staticmethod
    def get_category_with_subcategories(db: Session, slug: str):

        category = CategoryRepository.get_category_by_slug(db, slug)

        if not category:
            return None

        subcategories = CategoryRepository.get_subcategories(db, category.id)

        return {
            "category": category,
            "subcategories": subcategories
        }