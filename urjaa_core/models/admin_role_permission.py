from sqlalchemy import Column, ForeignKey, Integer

from urjaa_core.models.base import Base


class AdminRolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "admin"}

    role_id = Column(Integer, ForeignKey("admin.roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("admin.permissions.id", ondelete="CASCADE"), primary_key=True)
