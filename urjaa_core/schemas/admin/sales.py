from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field


class SalesSummaryResponse(BaseModel):
    active_products: int
    draft_products: int
    archived_products: int
    featured_products: int
    total_variants: int
    in_stock_variants: int
    out_of_stock_variants: int
    estimated_catalog_value: float
    currency: str = "INR"
    note: str


class CustomerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    store_id: UUID | None = None
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=150)
    address: str | None = None
    feedback: str | None = None


class CustomerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    store_id: UUID | None = None
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=150)
    address: str | None = None
    feedback: str | None = None


class CustomerResponse(BaseModel):
    id: UUID
    name: str
    store_id: UUID | None = None
    store_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    feedback: str | None = None
    source: Literal["WEBSITE", "STORE", "ADMIN"]
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        orm_mode = True


class SaleCreateRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    customer_id: UUID | None = None
    quantity: int = Field(gt=0)
    weight: float | None = Field(default=None, ge=0)
    final_price: float = Field(ge=0)
    date_time: datetime | None = None


class BulkSaleItemRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(gt=0)
    weight: float | None = Field(default=None, ge=0)
    final_price: float = Field(ge=0)


class BulkSaleCreateRequest(BaseModel):
    customer_id: UUID | None = None
    date_time: datetime | None = None
    items: list[BulkSaleItemRequest] = Field(min_items=1)


class SaleResponse(BaseModel):
    id: UUID
    invoice_number: str | None = None
    order_id: UUID | None = None
    product_id: UUID
    product_name: str
    variant_id: UUID
    sku_code: str | None = None
    customer_id: UUID | None = None
    customer_name: str | None = None
    quantity: int
    total_amount: float
    final_price: float
    cost_price: float
    profit: float
    source: Literal["store", "website"]
    status: Literal["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED", "COMPLETED"]
    date_time: datetime
    stock_after: int
    is_low_stock: bool
    is_out_of_stock: bool


class BulkSaleResponse(BaseModel):
    created_sale_ids: list[UUID]
    total_amount: float
    total_cost_price: float
    total_profit: float


class SalesHistoryResponse(BaseModel):
    items: list[SaleResponse]


class PaginatedSalesHistoryResponse(BaseModel):
    items: list[SaleResponse]
    page: int
    limit: int
    total: int
    pages: int


class StockAlertItemResponse(BaseModel):
    product_id: UUID
    product_name: str
    variant_id: UUID
    sku_code: str | None = None
    stock_quantity: int


class SalesStockOverviewResponse(BaseModel):
    low_stock_threshold: int
    low_stock_count: int
    out_of_stock_count: int
    low_stock_items: list[StockAlertItemResponse]
    out_of_stock_items: list[StockAlertItemResponse]


class PaginatedCustomersResponse(BaseModel):
    items: list[CustomerResponse]
    page: int
    limit: int
    total: int
    pages: int


class CustomerArchiveResponse(BaseModel):
    message: str


class SaleInvoiceResponse(BaseModel):
    sale_id: UUID
    invoice_number: str
    generated_at: datetime
