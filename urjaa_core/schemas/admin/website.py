from pydantic import BaseModel


class WebsiteOverviewResponse(BaseModel):
    total_categories: int
    total_subcategories: int
    total_collections: int
    total_featured_collections: int
    total_tags: int
    recent_product_updates: int
