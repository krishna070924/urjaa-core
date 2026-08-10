from sqlalchemy import Column, Integer, String, Text

from urjaa_core.models.base import Base


class AdminPermission(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "admin"}

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
