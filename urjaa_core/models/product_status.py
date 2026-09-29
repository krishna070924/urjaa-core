from sqlalchemy import Column, Integer, String

from urjaa_core.models.base import Base


class ProductStatus(Base):
    """Publication state of a product: draft, active, hidden, archived.

    A lookup rather than enum text so staff-facing labels can change without a
    migration. NOT the same question as `is_visible_on_website` ("should
    customers see it") or `deleted_at` ("has this been removed") — those are
    deliberately separate, because `archived` used to mean all three at once.
    """

    __tablename__ = "product_statuses"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False, unique=True)
