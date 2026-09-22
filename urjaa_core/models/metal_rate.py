from sqlalchemy import CheckConstraint, Column, Integer, Numeric, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from urjaa_core.models.base import Base


class MetalRate(Base):
    __tablename__ = "metal_rates"
    __table_args__ = (
        CheckConstraint("rate_per_gram > 0", name="chk_metal_rates_rate_positive"),
        UniqueConstraint("base_metal_id", "effective_from", name="uq_metal_rates_base_metal_effective_from"),
    )

    id = Column(Integer, primary_key=True)

    base_metal_id = Column(
        Integer,
        ForeignKey("base_metals.id", ondelete="CASCADE"),
        nullable=False
    )

    rate_per_gram = Column(Numeric(12, 2), nullable=False)

    effective_from = Column(TIMESTAMP, nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.now())

    base_metal = relationship("BaseMetal")