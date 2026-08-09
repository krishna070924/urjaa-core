from sqlalchemy.orm import Session
from uuid import UUID

from urjaa_core.models.product_variant import ProductVariant
from urjaa_core.models.product import Product


class VariantRepository:

    @staticmethod
    def get_variants_by_product(db: Session, store_id: UUID, product_id):

        return (
            db.query(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .filter(
                ProductVariant.product_id == product_id,
                ProductVariant.status == "active",
                Product.store_id == store_id,
            )
            .all()
        )