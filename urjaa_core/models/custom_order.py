from sqlalchemy import Column, Date, ForeignKey, Index, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class CustomOrder(Base):
    """O-04/D44: an offline bespoke order tracked through the Kanban board.
    Status moves and karigar assignment are logged to CustomOrderEvent
    (who/when) rather than only overwriting status_id."""

    __tablename__ = "custom_orders"
    __table_args__ = (
        Index("ix_custom_orders_store_id_status_id", "store_id", "status_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)

    customer_name = Column(String(120), nullable=False)
    customer_phone = Column(String(15), nullable=False)
    taken_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    taken_by_admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    karigar_id = Column(Integer, ForeignKey("karigars.id"), nullable=True, index=True)
    status_id = Column(Integer, ForeignKey("custom_order_statuses.id"), nullable=False)
    design_notes = Column(Text, nullable=True)
    reference_image_urls = Column(JSONB, nullable=False, default=list)
    expected_date = Column(Date, nullable=True)
    # POS: set when a sold piece is left at the counter for alteration.
    sale_order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    store = relationship("Store")
    karigar = relationship("Karigar")
    status = relationship("CustomOrderStatus")
    taken_by_admin = relationship("AdminUser", foreign_keys=[taken_by_admin_id])
    events = relationship(
        "CustomOrderEvent", back_populates="order", order_by="CustomOrderEvent.at"
    )
