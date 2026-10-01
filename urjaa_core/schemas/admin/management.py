from decimal import Decimal
from typing import Annotated, Literal
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from urjaa_core.models.product_stone import CERTIFICATION_AGENCIES


ProductStatus = Literal["draft", "active", "hidden", "archived"]
ProductGender = Literal["men", "women", "unisex", "kids"]  # mirrors the genders table


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
    base_metal_id: int | None = Field(default=None, gt=0)
    metal_type: str | None = Field(default=None, min_length=1, max_length=50)
    metal_color_id: int | None = Field(default=None, gt=0)
    metal_purity_id: int | None = Field(default=None, gt=0)
    # D25/H-10: the combination FK. May be given instead of, or alongside, the
    # three legacy ids above -- the service resolves/validates one against the
    # other (additive-first; legacy columns drop later per H-06).
    metal_id: int | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, gt=0)
    metal_weight_grams: float | None = Field(default=None, ge=0)
    stone_quantity: int | None = Field(default=0, ge=0)
    stone_cost: float | None = Field(default=0, ge=0)
    making_charges: float | None = Field(default=0, ge=0)
    cost_price: float | None = Field(default=0, ge=0)
    price_override: float | None = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    # Blank -> generated server-side (H-04); a jeweller's own numbering is honoured.
    sku_code: str | None = Field(default=None, max_length=100)
    internal_notes: str | None = Field(default=None)
    huid_number: str | None = Field(default=None, max_length=50)
    # D21/H-10: the one variation dimension (ring size, length, ...).
    size_value: str | None = Field(default=None, max_length=50)
    # H-10: one-off descriptor, display-only.
    spec_note: str | None = Field(default=None, max_length=200)

    @field_validator("size_value")
    @classmethod
    def _strip_size_value(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class VariantUpdateRequest(BaseModel):
    base_metal_id: int | None = Field(default=None, gt=0)
    metal_type: str | None = Field(default=None, min_length=1, max_length=50)
    metal_color_id: int | None = Field(default=None, gt=0)
    metal_purity_id: int | None = Field(default=None, gt=0)
    metal_id: int | None = Field(default=None, gt=0)
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
    size_value: str | None = Field(default=None, max_length=50)
    spec_note: str | None = Field(default=None, max_length=200)

    @field_validator("size_value")
    @classmethod
    def _strip_size_value(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


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
    # H-10: this row's stones, in total (quantity x unit price) -- see
    # product_stones.cost / pricing_service._stone_cost.
    cost: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    # H-05: folded back from urjaa-admin-backend's local B-02 extension now
    # that core isn't locked -- hand-entered certification (D13), all
    # nullable (D3), never required to create a product or variant.
    cut: str | None = Field(default=None, max_length=50)
    clarity: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=20)
    origin: str | None = Field(default=None, max_length=100)
    certificate_number: str | None = Field(default=None, max_length=100)
    certification_agency: str | None = Field(default=None, max_length=10)

    @field_validator("certification_agency")
    @classmethod
    def _validate_certification_agency(cls, v: str | None) -> str | None:
        if v is not None and v not in CERTIFICATION_AGENCIES:
            raise ValueError(f"certification_agency must be one of {', '.join(CERTIFICATION_AGENCIES)}")
        return v


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
    # D21/H-01: what this subcategory's single variation dimension is called,
    # and in what unit (e.g. "Ring Size" / "US"). Blank means products here
    # don't vary by size -- the service rejects a unit given without a label.
    size_label: str | None = Field(default=None, max_length=50)
    size_unit: str | None = Field(default=None, max_length=20)

    @field_validator("size_label", "size_unit")
    @classmethod
    def _strip_size_fields(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class SubcategoryUpdateRequest(BaseModel):
    category_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    size_label: str | None = Field(default=None, max_length=50)
    size_unit: str | None = Field(default=None, max_length=20)

    @field_validator("size_label", "size_unit")
    @classmethod
    def _strip_size_fields(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


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


class MetalCombinationGenerateRequest(BaseModel):
    """D26: staff pick a base metal plus the colours and purities it comes
    in; the service creates the missing cross-product `metals` rows."""

    base_metal_id: int = Field(gt=0)
    metal_color_ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=25)]
    metal_purity_ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=25)]


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
    size_label: str | None = None
    size_unit: str | None = None

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
    # D23: lets the admin narrow colours to the chosen base metal.
    base_metal_id: int | None = None

    class Config:
        orm_mode = True


class AdminMetalRateLookupResponse(BaseModel):
    id: int
    base_metal_id: int
    base_metal_name: str | None
    rate_per_gram: float
    effective_from: datetime


class AdminMetalCombinationResponse(BaseModel):
    id: int
    base_metal_id: int
    base_metal_name: str | None
    metal_color_id: int
    metal_color_name: str | None
    metal_purity_id: int
    metal_purity_label: str | None
    display_name: str | None


class MetalCombinationGenerateResponse(BaseModel):
    created: list[AdminMetalCombinationResponse]
    skipped: list[AdminMetalCombinationResponse]
    created_count: int
    skipped_count: int


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
    # H-11: derived from products.gender_id (D21/H-08), not EAV.
    gender: ProductGender | None = None
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
    # D21/H-01: the one variation dimension (ring size, length, ...). Display
    # label (attribute_label) and its unit/label come from the subcategory.
    size_value: str | None = None
    spec_note: str | None = None
    attribute_label: str | None = None
    base_metal_id: int | None
    metal_type: str | None
    metal_color_id: int | None
    metal_purity_id: int | None
    # D25/H-07: the one FK that matters going forward; base_metal_id /
    # metal_color_id / metal_purity_id above are legacy, kept until every
    # reader is migrated (H-06). *_name/_label resolve through metal_id with
    # legacy fallback -- same properties the storefront's VariantResponse uses.
    metal_id: int | None = None
    base_metal_name: str | None = None
    metal_color_name: str | None = None
    metal_purity_label: str | None = None
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
    # H-10: row total cost, persisted on product_stones.cost.
    cost: float | None = None
    # H-05: folded back from the admin-backend's local B-02 extension.
    cut: str | None = None
    clarity: str | None = None
    color: str | None = None
    origin: str | None = None
    certificate_number: str | None = None
    certification_agency: str | None = None


class AdminProductDetailResponse(AdminProductResponse):
    variants: list[AdminVariantResponse]
    images: list[AdminImageResponse]
    collection_ids: list[int]
    tag_ids: list[int]
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
