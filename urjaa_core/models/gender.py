from sqlalchemy import Column, Integer, String

from urjaa_core.models.base import Base


class Gender(Base):
    """Who a piece is intended for. Previously stored in the EAV
    `product_attributes` tables, which H-06 removes — this gives it a real home
    before that happens.
    """

    __tablename__ = "genders"

    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False, unique=True)
