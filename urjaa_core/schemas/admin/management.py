from typing import Literal
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


ProductStatus = Literal["draft", "active", "hidden", "archived"]
ProductGender = Literal["men", "women", "unisex"]


class ProductCreateVariantItem(BaseModel):
    stock_quantity: int = Field(default=0, ge=0)
    price_override: float | None = Field(default=None, ge=0)
    sku_code: str | None = Field(default=None, min_length=1, max_length=100)


class ProductCreateImageItem(BaseModel):
    image_url: str = Field(min_length=1)
    is_primary: bool = False
    display_order: int | None = Field(default=None, ge=0)


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = None
    category_id: int = Field(gt=0)
    subcategory_id: int = Field(gt=0)
    collection_id: int | None = Field(default=None, gt=0)
    collection_ids: list[int] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    featured: bool = False
    customizable: bool = False
    status: ProductStatus = "draft"
    gender: ProductGender = "unisex"
    variants: list[ProductCreateVariantItem] = Field(default_factory=list)
    images: list[ProductCreateImageItem] = Field(default_factory=list)


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category_id: int | None = Field(default=None, gt=0)
    subcategory_id: int | None = Field(default=None, gt=0)
    featured: bool | None = None
    customizable: bool | None = None
    status: ProductStatus | None = None
    gender: ProductGender | None = None


class VariantCreateRequest(BaseModel):
    attribute_value_ids: list[int] = Field(default_factory=list)
    base_metal_id: int | None = Field(default=None, gt=0)
    metal_type: str | None = Field(default=None, min_length=1, max_length=50)
    metal_color_id: int | None = Field(default=None, gt=0)
    metal_purity_id: int | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, gt=0)
    metal_weight_grams: float | None = Field(default=None, ge=0)
    stone_quantity: int | None = Field(default=0, ge=0)
    stone_cost: float | None = Field(default=0, ge=0)
    making_charges: float | None = Field(default=0, ge=0)
    cost_price: float | None = Field(default=0, ge=0)
    price_override: float | None = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    sku_code: str = Field(min_length=1, max_length=100)
    internal_notes: str | None = Field(default=None)
    huid_number: str | None = Field(default=None, max_length=50)


class VariantUpdateRequest(BaseModel):
    attribute_value_ids: list[int] = Field(default_factory=list)
    base_metal_id: int | None = Field(default=None, gt=0)
    metal_type: str | None = Field(default=None, min_length=1, max_length=50)
    metal_color_id: int | None = Field(default=None, gt=0)
    metal_purity_id: int | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, gt=0)
    metal_weight_grams: float | None = Field(default=None, ge=0)
    stone_quantity: int | None = Field(default=None, ge=0)
    stone_cost: float | None = Field(default=None, ge=0)
    making_charges: float | None = Field(default=None, ge=0)
    cost_price: float | None = Field(default=None, ge=0)
    price_override: float | None = Field(default=None, ge=0)
    stock_quantity: int | None = Field(default=None, ge=0)
    sku_code: str | None = Field(default=None, min_length=1, max_length=100)
    internal_notes: str | None = Field(default=None)
    huid_number: str | None = Field(default=None, max_length=50)


class ImageCreateRequest(BaseModel):
    image_url: str = Field(min_length=1)
    is_primary: bool = False
    display_order: int | None = Field(default=None, ge=0)


class ImageReorderRequest(BaseModel):
    product_id: UUID
    image_ids: list[int] = Field(min_items=1)


class ProductRelationsUpdateRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)


class StoneAssignmentItem(BaseModel):
    stone_id: int = Field(gt=0)
    quantity: int | None = Field(default=None, ge=0)
    total_carat_weight: float | None = Field(default=None, ge=0)


class ProductStonesUpdateRequest(BaseModel):
    stones: list[StoneAssignmentItem] = Field(default_factory=list)


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_order: int | None = None


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    display_order: int | None = None


class SubcategoryCreateRequest(BaseModel):
    category_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    default_variant_type_id: int | None = Field(default=None, gt=0)


class SubcategoryUpdateRequest(BaseModel):
    category_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_variant_type_id: int | None = Field(default=None, gt=0)


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    banner_image: str | None = None
    is_featured: bool = False
    display_order: int | None = None


class CollectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    banner_image: str | None = None
    is_featured: bool | None = None
    display_order: int | None = None


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class TagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class StoneCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class StoneUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class AttributeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    filterable: bool = True


class AttributeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    filterable: bool | None = None


class AttributeValueCreateRequest(BaseModel):
    attribute_id: int = Field(gt=0)
    value: str = Field(min_length=1, max_length=100)


class AttributeValueUpdateRequest(BaseModel):
    attribute_id: int | None = Field(default=None, gt=0)
    value: str | None = Field(default=None, min_length=1, max_length=100)


class MetalRateCreateRequest(BaseModel):
    base_metal_id: int = Field(gt=0)
    rate_per_gram: float = Field(gt=0)
    effective_from: datetime


class MetalRateUpdateItem(BaseModel):
    id: int = Field(gt=0)
    rate_per_gram: float = Field(ge=0)
    effective_from: datetime


class MetalRateBulkUpdateRequest(BaseModel):
    rates: list[MetalRateUpdateItem] = Field(default_factory=list)
    gold_rate_per_gram: float | None = Field(default=None, ge=0)
    silver_rate_per_gram: float | None = Field(default=None, ge=0)
    effective_from: datetime | None = None


class VariantTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    display_order: int | None = None
    attribute_ids: list[int] = Field(default_factory=list)


class VariantTypeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    display_order: int | None = None
    attribute_ids: list[int] | None = None


class MetalTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class MetalTypeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)


class MetalPurityCreateRequest(BaseModel):
    base_metal_id: int = Field(gt=0)
    purity_label: str = Field(min_length=1, max_length=20)
    numeric_purity: float = Field(ge=0)


class MetalPurityUpdateRequest(BaseModel):
    base_metal_id: int | None = Field(default=None, gt=0)
    purity_label: str | None = Field(default=None, min_length=1, max_length=20)
    numeric_purity: float | None = Field(default=None, ge=0)


class MetalColorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class MetalColorUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)


class StoreCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class StoreUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AdminStoreResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        orm_mode = True


class AdminStoresBootstrapResponse(BaseModel):
    stores: list[AdminStoreResponse]
    default_store_id: UUID | None = None


class AdminCategoryLookupResponse(BaseModel):
    id: int
    name: str
    slug: str
    display_order: int | None = None
    is_active: bool = True
    is_deleted: bool = False

    class Config:
        orm_mode = True


class AdminSubcategoryLookupResponse(BaseModel):
    id: int
    category_id: int | None
    name: str
    slug: str
    default_variant_type_id: int | None = None

    class Config:
        orm_mode = True


class AdminVariantTypeLookupResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    display_order: int | None = None
    attribute_ids: list[int] = Field(default_factory=list)

    class Config:
        orm_mode = True


class AdminCollectionLookupResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    banner_image: str | None = None
    is_featured: bool = False
    display_order: int | None = None

    class Config:
        orm_mode = True


class AdminTagLookupResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None

    class Config:
        orm_mode = True


class AdminStoneLookupResponse(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class AdminAttributeValueLookupResponse(BaseModel):
    id: int
    attribute_id: int | None = None
    attribute_name: str | None = None
    value: str | None

    class Config:
        orm_mode = True


class AdminAttributeLookupResponse(BaseModel):
    id: int
    name: str | None
    slug: str | None
    filterable: bool | None = None
    values: list[AdminAttributeValueLookupResponse]


class AdminMetalPurityLookupResponse(BaseModel):
    id: int
    base_metal_id: int | None
    base_metal_name: str | None
    purity_label: str | None
    numeric_purity: float | None


class AdminMetalTypeLookupResponse(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class AdminMetalColorLookupResponse(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class AdminMetalRateLookupResponse(BaseModel):
    id: int
    base_metal_id: int
    base_metal_name: str | None
    rate_per_gram: float
    effective_from: datetime


class AdminProductResponse(BaseModel):
    id: UUID
    store_id: UUID | None = None
    store_name: str | None = None
    name: str
    slug: str
    description: str | None
    category_id: int | None = None
    subcategory_id: int | None = None
    featured: bool
    customizable: bool
    status: ProductStatus
    starting_price: float | None = None
    created_at: datetime | None = None
    variant_count: int | None = None
    image_url: str | None = None
    store_count: int | None = None
    primary_store_id: UUID | None = None
    store_ids: list[UUID] | None = None
    store_product_refs: list[dict[str, UUID]] | None = None

    class Config:
        orm_mode = True


class AdminProductListResponse(BaseModel):
    items: list[AdminProductResponse]
    page: int
    limit: int
    total: int
    pages: int


class AdminVariantResponse(BaseModel):
    id: UUID
    product_id: UUID
    attribute_values: list[AdminAttributeValueLookupResponse] = Field(default_factory=list)
    base_metal_id: int | None
    metal_type: str | None
    metal_color_id: int | None
    metal_purity_id: int | None
    weight: float | None
    metal_weight_grams: float | None
    stone_quantity: int | None = None
    stone_cost: float | None = None
    making_charges: float | None = None
    cost_price: float | None = None
    price_override: float | None = None
    stock_quantity: int
    sku_code: str | None
    internal_notes: str | None = None
    huid_number: str | None = None

    class Config:
        orm_mode = True


class AdminImageResponse(BaseModel):
    id: int
    product_id: UUID
    image_url: str
    is_primary: bool
    display_order: int | None

    class Config:
        orm_mode = True


class AdminStoneRelationItem(BaseModel):
    stone_id: int
    quantity: int | None
    total_carat_weight: float | None


class AdminProductDetailResponse(AdminProductResponse):
    variants: list[AdminVariantResponse]
    images: list[AdminImageResponse]
    collection_ids: list[int]
    tag_ids: list[int]
    attribute_value_ids: list[int]
    stones: list[AdminStoneRelationItem]


class MessageResponse(BaseModel):
    message: str


class DeleteResultResponse(BaseModel):
    success: bool
    deleted: bool


class SetPrimaryImageResponse(BaseModel):
    message: str
    image_id: int


class AdminBulkUploadRowErrorResponse(BaseModel):
    row_number: int
    errors: list[str]


class AdminBulkUploadProductsResponse(BaseModel):
    success: bool
    inserted_products: int = 0
    inserted_variants: int = 0
    errors: list[AdminBulkUploadRowErrorResponse] = Field(default_factory=list)


class AdminDashboardMetalRatesResponse(BaseModel):
    gold_22k: float | None = None
    gold_18k: float | None = None
    silver: float | None = None
    gold_trend: int = 0
    silver_trend: int = 0
    effective_from: datetime | None = None


class AdminDashboardPricingSnapshotResponse(BaseModel):
    average_price: float | None = None
    highest_price: float | None = None
    lowest_price: float | None = None


class AdminDashboardLowStockItemResponse(BaseModel):
    product_id: UUID
    product_name: str
    sku_code: str | None = None
    stock_quantity: int


class AdminDashboardTopSellingProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    units_sold: int
    revenue: float
    sales_count: int


class AdminDashboardSummaryResponse(BaseModel):
    total_products: int
    total_variants: int
    total_collections: int
    active_products: int
    low_stock_count: int
    total_revenue: float = 0
    total_profit: float = 0
    profit_margin: float = 0
    store_revenue: float = 0
    website_revenue: float = 0
    total_sales_count: int = 0
    top_selling_products: list[AdminDashboardTopSellingProductResponse] = Field(default_factory=list)
    low_stock_items: list[AdminDashboardLowStockItemResponse]
    recent_products: list[AdminProductResponse]
    metal_rates: AdminDashboardMetalRatesResponse
    pricing_snapshot: AdminDashboardPricingSnapshotResponse


class AdminDashboardDailyRevenuePointResponse(BaseModel):
    date: date
    store: float = 0
    website: float = 0
    profit: float = 0


class AdminDashboardTrendsResponse(BaseModel):
    daily_revenue: list[AdminDashboardDailyRevenuePointResponse] = Field(default_factory=list)
