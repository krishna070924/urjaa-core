from sqlalchemy import Column, Integer, String

from urjaa_core.models.base import Base

# D44: the fixed Kanban vocabulary, in board order. Seeded by migration
# 0031_custom_orders -- not admin-editable, so these codes are a stable
# source of truth for status_id lookups across the service layer.
ORDER_TAKEN = "order_taken"
DESIGN_FINALISED = "design_finalised"
WITH_KARIGAR = "with_karigar"
QUALITY_CHECK = "quality_check"
READY_FOR_PICKUP = "ready_for_pickup"
DELIVERED = "delivered"
CANCELLED = "cancelled"

CUSTOM_ORDER_STATUS_CODES = (
    ORDER_TAKEN,
    DESIGN_FINALISED,
    WITH_KARIGAR,
    QUALITY_CHECK,
    READY_FOR_PICKUP,
    DELIVERED,
    CANCELLED,
)

# D44: moving a custom order OUT of one of these requires the explicit
# reopen=true flag (see AdminCustomOrderService.set_status).
TERMINAL_STATUS_CODES = (DELIVERED, CANCELLED)


class CustomOrderStatus(Base):
    __tablename__ = "custom_order_statuses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(30), nullable=False, unique=True)
    label = Column(String(60), nullable=False)
    display_order = Column(Integer, nullable=False)
