from pydantic import BaseModel
from uuid import UUID
from typing import Any


class ProductBase(BaseModel):
    id: UUID
    name: str
    slug: str
    featured: bool
    customizable: bool
    category_id: int | None = None
    collection_id: int | None = None


class ProductImageSchema(BaseModel):
    image_url: str
    is_primary: bool
    display_order: int

    class Config:
        orm_mode = True

class ProductResponse(ProductBase):
    starting_price: float | None = None
    formatted_price: str = ""
    images: list[ProductImageSchema] = []   # 👈 ADD THIS

    class Config:
        orm_mode = True

class PaginatedProducts(BaseModel):
    items: list[ProductResponse]
    page: int
    limit: int
    total: int
    pages: int
    filters: dict[str, Any] | None = None

class VariantResponse(BaseModel):

    id: UUID
    size: str | None
    metal_weight_grams: float | None
    stock_quantity: int
    sku_code: str

    class Config:
        orm_mode = True

class ProductDetailResponse(ProductBase):

    description: str | None
    status: str
    starting_price: float | None = None
    formatted_price: str = ""

    variants: list[VariantResponse]
    images: list[ProductImageSchema] = []   # 👈 ADD THIS

    class Config:
        orm_mode = True



