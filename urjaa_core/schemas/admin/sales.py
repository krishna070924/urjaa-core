from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from urjaa_core.schemas.order import OrderItemResponse, OrderResponse


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
    store_credit_balance: float = 0
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
    # Review 8: on-the-spot discount (₹) given at the counter; final_price is
    # already net of it. Shown on the invoice.
    discount_amount: float = Field(default=0, ge=0)
    date_time: datetime | None = None
    # D22: required for items tracked piece by piece — which pieces left the counter.
    unit_ids: list[int] | None = None


class SaleAlterationRequest(BaseModel):
    """POS: customer bought the piece but left it at the counter for resizing."""

    what: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    ready_by: date


class BulkSaleItemRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(gt=0)
    weight: float | None = Field(default=None, ge=0)
    final_price: float = Field(ge=0)
    # Review 8: on-the-spot discount (₹) given at the counter; final_price is
    # already net of it. Shown on the invoice.
    discount_amount: float = Field(default=0, ge=0)
    unit_ids: list[int] | None = None
    alteration: SaleAlterationRequest | None = None


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class SalePaymentRequest(BaseModel):
    method: Literal["cash", "upi", "card", "split"]
    # Split only: amount per method -- must add up to the amount to pay.
    cash: float = Field(default=0, ge=0)
    upi: float = Field(default=0, ge=0)
    card: float = Field(default=0, ge=0)
    reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class OldGoldItemRequest(BaseModel):
    """Old jewellery handed in against this bill. rate_per_gram is for this
    purity (staff may edit the suggested rate); the server works out the value."""

    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    base_metal_id: int
    purity: float = Field(gt=0, le=100)  # percent
    gross_weight: float = Field(gt=0)
    stone_weight: float = Field(default=0, ge=0)
    rate_per_gram: float = Field(gt=0)
    deduction_amount: float = Field(default=0, ge=0)
    deduction_reason: ShortText | None = None


class BulkSaleCreateRequest(BaseModel):
    customer_id: UUID | None = None
    date_time: datetime | None = None
    items: list[BulkSaleItemRequest] = Field(min_items=1)
    # Optional for API compatibility; the POS always sends it. NULL = "—" on the bill.
    payment: SalePaymentRequest | None = None
    store_credit_used: float = Field(default=0, ge=0)
    old_gold: list[OldGoldItemRequest] = Field(default_factory=list)
    # When old jewellery is worth more than the bill: how the difference goes back.
    payout_method: Literal["cash", "upi", "store_credit"] | None = None


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
    total_amount: Decimal
    final_price: Decimal
    discount_amount: Decimal = Decimal("0")
    cost_price: Decimal
    profit: Decimal
    source: Literal["store", "website"]
    status: Literal["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED", "COMPLETED"]
    date_time: datetime
    stock_after: int
    is_low_stock: bool
    is_out_of_stock: bool
    returned_quantity: int = 0
    credit_notes: list[dict] = Field(default_factory=list)  # [{id, credit_note_number}]


class BulkSaleAlterationResponse(BaseModel):
    custom_order_id: int
    product_name: str
    ready_by: date


class BulkSaleResponse(BaseModel):
    created_sale_ids: list[UUID]
    order_id: UUID | None = None
    invoice_number: str | None = None
    # total_amount = ex-GST, after discount; grand_total = what was collected.
    total_amount: float
    tax_amount: float = 0
    grand_total: float = 0
    alterations: list[BulkSaleAlterationResponse] = Field(default_factory=list)
    total_cost_price: float
    total_profit: float
    old_gold_total: float = 0
    store_credit_used: float = 0
    amount_to_pay: float = 0
    payable_to_customer: float = 0
    payout_method: str | None = None


class SaleReturnLineRequest(BaseModel):
    sale_id: UUID
    quantity: int = Field(gt=0)
    unit_ids: list[int] = Field(default_factory=list)  # pieces coming back, for items tracked by HUID


class SaleReturnCreateRequest(BaseModel):
    lines: list[SaleReturnLineRequest] = Field(min_length=1)
    reason: Literal["defect", "size", "changed_mind", "exchange", "other"]
    reason_note: ShortText | None = None
    deduction_amount: float = Field(default=0, ge=0)
    deduction_reason: ShortText | None = None
    refund_method: Literal["cash", "upi", "card", "store_credit"]
    refund_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    # Walk-in bill refunded to store credit: the customer to credit.
    customer_id: UUID | None = None


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
    order_id: UUID
    invoice_number: str
    generated_at: datetime


# H-05 (Added by H-03): staff need to see which physical piece was
# reserved/sold for a website order line. HUIDs are staff-only (D22) and must
# never reach the storefront-facing OrderResponse, so this widens it only for
# the admin order endpoints.
class AdminOrderItemResponse(OrderItemResponse):
    huid_numbers: list[str] = Field(default_factory=list)


class AdminOrderResponse(OrderResponse):
    items: list[AdminOrderItemResponse]


class AdminPaginatedOrdersResponse(BaseModel):
    items: list[AdminOrderResponse]
    page: int
    limit: int
    total: int
    pages: int
