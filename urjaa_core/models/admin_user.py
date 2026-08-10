from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String

from urjaa_core.models.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(50), nullable=False, default="super_admin", server_default="super_admin")
    # roles now lives in the "admin" schema (URJ repo-split Task 4.1: RBAC
    # tables isolated so the storefront DB role structurally cannot read them).
    role_id = Column(Integer, ForeignKey("admin.roles.id", ondelete="SET NULL"), nullable=True, index=True)
    permissions = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
