from uuid import UUID

from sqlalchemy.orm import Session

from urjaa_core.repositories.admin.website_repository import WebsiteRepository


class WebsiteService:
    @staticmethod
    def get_overview(db: Session, store_id: UUID) -> dict:
        return {
            "total_categories": WebsiteRepository.count_categories(db),
            "total_subcategories": WebsiteRepository.count_subcategories(db),
            "total_collections": WebsiteRepository.count_collections(db),
            "total_featured_collections": WebsiteRepository.count_featured_collections(db),
            "total_tags": WebsiteRepository.count_tags(db),
            "recent_product_updates": WebsiteRepository.count_recent_product_updates(db, store_id=store_id),
        }
