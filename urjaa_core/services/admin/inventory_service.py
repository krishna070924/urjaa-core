import csv
from io import StringIO
from uuid import UUID

from sqlalchemy.orm import Session

from urjaa_core.repositories.admin.inventory_repository import InventoryRepository


class InventoryService:
    @staticmethod
    def get_summary(db: Session, store_id: UUID, low_stock_threshold: int = 5, low_stock_limit: int = 10) -> dict:
        low_stock_rows = InventoryRepository.get_low_stock_variants(
            db,
            threshold=low_stock_threshold,
            store_id=store_id,
            limit=low_stock_limit,
        )
        out_of_stock_rows = InventoryRepository.get_out_of_stock_variants(db, store_id=store_id, limit=low_stock_limit)

        low_stock_items = [
            {
                "product_id": product.id,
                "product_name": product.name,
                "variant_id": variant.id,
                "sku_code": variant.sku_code,
                "stock_quantity": variant.stock_quantity,
            }
            for variant, product in low_stock_rows
        ]

        out_of_stock_items = [
            {
                "product_id": product.id,
                "product_name": product.name,
                "variant_id": variant.id,
                "sku_code": variant.sku_code,
                "stock_quantity": variant.stock_quantity,
            }
            for variant, product in out_of_stock_rows
        ]

        return {
            "total_variants": InventoryRepository.count_variants(db, store_id=store_id),
            "total_stock_units": InventoryRepository.total_stock_units(db, store_id=store_id),
            "low_stock_threshold": low_stock_threshold,
            "low_stock_count": InventoryRepository.count_low_stock_variants(db, low_stock_threshold, store_id=store_id),
            "out_of_stock_count": InventoryRepository.count_out_of_stock_variants(db, store_id=store_id),
            "low_stock_items": low_stock_items,
            "out_of_stock_items": out_of_stock_items,
        }

    @staticmethod
    def get_export_rows(db: Session, store_id: UUID) -> dict:
        rows = InventoryRepository.get_inventory_export_rows(db, store_id=store_id)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["product_id", "product_name", "variant_id", "sku_code", "stock_quantity", "status"])
        for variant, product in rows:
            status = "out_of_stock" if variant.stock_quantity <= 0 else "low_stock" if variant.stock_quantity <= 5 else "in_stock"
            writer.writerow(
                [
                    str(product.id),
                    product.name,
                    str(variant.id),
                    variant.sku_code or "",
                    variant.stock_quantity,
                    status,
                ]
            )
        return {"csv_text": output.getvalue()}
