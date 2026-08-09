from sqlalchemy import Column, Integer, String, Text

from urjaa_core.models.base import Base


class AdminRole(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
