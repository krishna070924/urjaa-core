from uuid import UUID

from pydantic import BaseModel


class InventoryLowStockItemResponse(BaseModel):
    product_id: UUID
    product_name: str
    variant_id: UUID
    sku_code: str | None = None
    stock_quantity: int


class InventorySummaryResponse(BaseModel):
    total_variants: int
    total_stock_units: int
    low_stock_threshold: int
    low_stock_count: int
    out_of_stock_count: int
    low_stock_items: list[InventoryLowStockItemResponse]
    out_of_stock_items: list[InventoryLowStockItemResponse]
