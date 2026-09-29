from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class Metal(Base):
    """One VALID combination of base metal, colour and purity — e.g.
    "22K Yellow Gold" (decision D25).

    A variant references one of these instead of carrying three independent
    FKs, which is what made "Gold / Silver" representable. An invalid pairing
    is not merely rejected here: no row exists for it, so it cannot be chosen.

    The three lookups stay normalised on purpose — denormalising would
    duplicate numeric_purity (a pricing input) across every colour and make
    renaming a colour a multi-row update.

    Rates are NOT on this table. Pricing is
    weight x rate(base_metal) x (numeric_purity/100) + stone + making, so
    colour has no effect on price and metal_rates stays keyed on base metal.
    """

    __tablename__ = "metals"
    __table_args__ = (
        UniqueConstraint(
            "base_metal_id",
            "metal_color_id",
            "metal_purity_id",
            name="uq_metals_combination",
        ),
    )

    id = Column(Integer, primary_key=True)

    base_metal_id = Column(Integer, ForeignKey("base_metals.id"), nullable=False)

    # NOT NULL, and not merely for tidiness: Postgres treats NULL as distinct
    # from NULL, so the UNIQUE constraint below stops preventing duplicates the
    # moment either column is nullable. A combination must be complete or the
    # guarantee this table exists to provide is silently switched off.
    #
    # Silver and platinum get a colour row of their own ("Silver", "Natural")
    # rather than a null — every metal has a colour, even when there is one.
    metal_color_id = Column(Integer, ForeignKey("metal_colors.id"), nullable=False)
    metal_purity_id = Column(Integer, ForeignKey("metal_purities.id"), nullable=False)

    # Generated ("22K Yellow Gold") but editable — a jeweller may have house
    # terminology.
    display_name = Column(String(120), nullable=True)

    base_metal = relationship("BaseMetal")
    metal_color = relationship("MetalColor")
    metal_purity = relationship("MetalPurity")
