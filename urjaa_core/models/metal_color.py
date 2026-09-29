from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from urjaa_core.models.base import Base


class MetalColor(Base):
    __tablename__ = "metal_colors"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)

    # D23: a colour belongs to a base metal — gold comes in yellow, white and
    # rose; silver does not come in rose. MetalPurity already had this FK;
    # MetalColor was a flat list, so nothing stopped a variant being saved as
    # Gold / Silver (which one in the dev database actually was).
    #
    # Nullable so a colour whose base metal is genuinely unknown can persist
    # rather than blocking the migration — see 0019, which leaves such rows
    # unmapped and reports them instead of guessing.
    base_metal_id = Column(Integer, ForeignKey("base_metals.id"), nullable=True)

    base_metal = relationship("BaseMetal")
