import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from urjaa_core.core.database import get_db
from urjaa_core.models.admin_permission import AdminPermission
from urjaa_core.models.admin_role import AdminRole
from urjaa_core.models.admin_role_permission import AdminRolePermission
from urjaa_core.models.admin_user import AdminUser


DEFAULT_ADMIN_JWT_TTL_SECONDS = 60 * 60 * 12
PBKDF2_ITERATIONS = 200_000

# H6 FIX: admin JWT now travels as an HttpOnly cookie instead of being stored in
# localStorage (XSS-readable). COOKIE_SECURE defaults to false because nothing in
# this stack serves HTTPS yet (nginx/TLS is a separate, already-deferred gap — see
# urjaa-infrastructure docs M9) — a Secure cookie would silently never be set/sent
# over the plain-http local stack. Set COOKIE_SECURE=true once TLS is wired up.
ADMIN_AUTH_COOKIE_NAME = "admin_token"
_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").strip().lower() == "true"


def set_admin_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=ADMIN_AUTH_COOKIE_NAME,
        value=token,
        max_age=_get_ttl_seconds(),
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def clear_admin_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_AUTH_COOKIE_NAME, path="/")

ADMIN_PERMISSION_MANAGE_USERS = "manage_admin_users"
ADMIN_PERMISSION_MANAGE_ROLES = "manage_roles"
ADMIN_PERMISSION_MANAGE_STORES = "manage_stores"
ADMIN_PERMISSION_MANAGE_STORE = "manage_store"
ADMIN_PERMISSION_MANAGE_WEBSITE = "manage_website"
ADMIN_PERMISSION_MANAGE_CMS = "manage_cms"
ADMIN_PERMISSION_MANAGE_CUSTOMERS = "manage_customers"
ADMIN_PERMISSION_MANAGE_INVENTORY = "manage_inventory"
ADMIN_PERMISSION_MANAGE_PRODUCTS = "manage_products"
ADMIN_PERMISSION_MANAGE_SALES = "manage_sales"
ADMIN_PERMISSION_VIEW_SALES = "view_sales"
ADMIN_PERMISSION_MANAGE_ORDERS = "manage_orders"
ADMIN_PERMISSION_VIEW_ORDERS = "view_orders"
ADMIN_PERMISSION_VIEW_REPORTS = "view_reports"
ADMIN_PERMISSION_VIEW_ANALYTICS = "view_analytics"
ADMIN_PERMISSION_MANAGE_TICKETS = "manage_tickets"
ADMIN_PERMISSION_VIEW_TICKETS = "view_tickets"
ADMIN_PERMISSION_MANAGE_CAMPAIGNS = "manage_campaigns"

ADMIN_PERMISSION_DESCRIPTIONS: dict[str, str] = {
    ADMIN_PERMISSION_MANAGE_USERS: "Manage admin users",
    ADMIN_PERMISSION_MANAGE_ROLES: "Manage role-permission assignments",
    ADMIN_PERMISSION_MANAGE_STORES: "Manage stores and store configuration",
    ADMIN_PERMISSION_MANAGE_STORE: "Manage store locations and store details",
    ADMIN_PERMISSION_MANAGE_INVENTORY: "Manage inventory controls and metal settings",
    ADMIN_PERMISSION_MANAGE_PRODUCTS: "Create, update and delete products",
    ADMIN_PERMISSION_MANAGE_CUSTOMERS: "Manage customer records and inbound contacts",
    ADMIN_PERMISSION_MANAGE_SALES: "Create and manage sales",
    ADMIN_PERMISSION_VIEW_SALES: "View sales data",
    ADMIN_PERMISSION_MANAGE_ORDERS: "Manage website orders",
    ADMIN_PERMISSION_VIEW_ORDERS: "View website orders",
    ADMIN_PERMISSION_MANAGE_WEBSITE: "Manage website CMS and website module",
    ADMIN_PERMISSION_MANAGE_CMS: "Manage website CMS and legal/SEO content",
    ADMIN_PERMISSION_VIEW_REPORTS: "View reports and newsletter exports",
    ADMIN_PERMISSION_VIEW_ANALYTICS: "View analytics and CRM data",
    ADMIN_PERMISSION_MANAGE_TICKETS: "Manage support tickets (reply, assign, resolve)",
    ADMIN_PERMISSION_VIEW_TICKETS: "View support tickets (read-only)",
    ADMIN_PERMISSION_MANAGE_CAMPAIGNS: "Create and send WhatsApp/email campaigns",
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "super_admin": "Full system access — all permissions including user and role management",
    "admin": "Admin access — full operational control, cannot manage other admin users or roles",
    "manager": "Operational management — products, inventory, orders, sales, CMS",
    "staff": "Operational staff — view and edit products, inventory, and order status; no financial or admin access",
    "support": "Support access — view orders, customers, sales, reports, and dashboard; no write access",
    "viewer": "Read-only access — view sales, orders, and reports only",
}

DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": set(ADMIN_PERMISSION_DESCRIPTIONS.keys()),
    "admin": {
        ADMIN_PERMISSION_MANAGE_WEBSITE,
        ADMIN_PERMISSION_MANAGE_CMS,
        ADMIN_PERMISSION_MANAGE_STORE,
        ADMIN_PERMISSION_MANAGE_INVENTORY,
        ADMIN_PERMISSION_MANAGE_PRODUCTS,
        ADMIN_PERMISSION_MANAGE_CUSTOMERS,
        ADMIN_PERMISSION_MANAGE_SALES,
        ADMIN_PERMISSION_VIEW_SALES,
        ADMIN_PERMISSION_MANAGE_ORDERS,
        ADMIN_PERMISSION_VIEW_ORDERS,
        ADMIN_PERMISSION_VIEW_REPORTS,
        ADMIN_PERMISSION_VIEW_ANALYTICS,
        ADMIN_PERMISSION_MANAGE_TICKETS,
        ADMIN_PERMISSION_VIEW_TICKETS,
        ADMIN_PERMISSION_MANAGE_CAMPAIGNS,
    },
    "manager": {
        ADMIN_PERMISSION_MANAGE_ORDERS,
        ADMIN_PERMISSION_VIEW_ORDERS,
        ADMIN_PERMISSION_MANAGE_INVENTORY,
        ADMIN_PERMISSION_MANAGE_PRODUCTS,
        ADMIN_PERMISSION_MANAGE_CUSTOMERS,
        ADMIN_PERMISSION_MANAGE_CMS,
        ADMIN_PERMISSION_MANAGE_STORE,
        ADMIN_PERMISSION_MANAGE_SALES,
        ADMIN_PERMISSION_VIEW_SALES,
        ADMIN_PERMISSION_VIEW_REPORTS,
        ADMIN_PERMISSION_VIEW_ANALYTICS,
        ADMIN_PERMISSION_MANAGE_TICKETS,
        ADMIN_PERMISSION_VIEW_TICKETS,
    },
    "staff": {
        ADMIN_PERMISSION_MANAGE_PRODUCTS,
        ADMIN_PERMISSION_MANAGE_INVENTORY,
        ADMIN_PERMISSION_MANAGE_ORDERS,
        ADMIN_PERMISSION_VIEW_ORDERS,
        ADMIN_PERMISSION_MANAGE_CUSTOMERS,
        ADMIN_PERMISSION_VIEW_TICKETS,
    },
    "support": {
        ADMIN_PERMISSION_VIEW_ORDERS,
        ADMIN_PERMISSION_VIEW_SALES,
        ADMIN_PERMISSION_VIEW_REPORTS,
        ADMIN_PERMISSION_MANAGE_CUSTOMERS,
        ADMIN_PERMISSION_VIEW_ANALYTICS,
        ADMIN_PERMISSION_MANAGE_TICKETS,
        ADMIN_PERMISSION_VIEW_TICKETS,
    },
    "viewer": {
        ADMIN_PERMISSION_VIEW_ORDERS,
        ADMIN_PERMISSION_VIEW_SALES,
        ADMIN_PERMISSION_VIEW_REPORTS,
        ADMIN_PERMISSION_VIEW_ANALYTICS,
        ADMIN_PERMISSION_VIEW_TICKETS,
    },
}

# Backward-compatible alias for existing imports.
ROLE_PERMISSIONS = DEFAULT_ROLE_PERMISSIONS

ROLE_ALIASES = {
    "superadmin": "super_admin",
}

# SECURITY FIX 1.2: Role hierarchy for privilege escalation prevention.
# Higher number = higher privilege level. A creator must have a strictly higher level than the role they grant.
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 1,
    "support": 2,
    "staff": 3,
    "manager": 4,
    "admin": 5,
    "super_admin": 6,
}

ALL_ADMIN_PERMISSIONS = sorted(ADMIN_PERMISSION_DESCRIPTIONS.keys())

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ADMIN_ROUTE_PERMISSION_RULES: list[dict[str, Any]] = [
    {
        "pattern": re.compile(r"^/admin/users(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_USERS},
    },
    {
        "pattern": re.compile(r"^/admin/roles(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_ROLES},
    },
    {
        "pattern": re.compile(r"^/admin/stores(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_STORES},
    },
    {
        "pattern": re.compile(r"^/admin/website-cms(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_WEBSITE},
    },
    {
        "pattern": re.compile(r"^/admin/website(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_WEBSITE},
    },
    {
        "pattern": re.compile(r"^/admin/(website-)?orders(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_ORDERS, ADMIN_PERMISSION_MANAGE_ORDERS},
    },
    {
        "pattern": re.compile(r"^/admin/(website-)?orders(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_ORDERS},
    },
    {
        "pattern": re.compile(r"^/admin/customers(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_ORDERS, ADMIN_PERMISSION_MANAGE_ORDERS, ADMIN_PERMISSION_MANAGE_CUSTOMERS},
    },
    {
        "pattern": re.compile(r"^/admin/customers(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/sales/customers(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/sales(?:/bulk)?$"),
        "methods": {"POST"},
        "any_of": {ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/sales/(summary|history|stock-overview|export)(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_SALES, ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/sales/[^/]+/invoice(?:/meta)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_SALES, ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/inventory/(summary|export)$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_INVENTORY},
    },
    {
        "pattern": re.compile(r"^/admin/inventory/products(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/inventory/variants(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/products(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/variants(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/images(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/(categories|subcategories|collections|tags|stones|attributes|attribute-values|variant-types)(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/(metal-types|metal-purities|metal-colors|metal-rates)(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_INVENTORY},
    },
    # FIX 4.1: Add explicit GET permission rules for routes previously unprotected (fail-closed from Fix 1.3)
    {
        "pattern": re.compile(r"^/admin/(categories|subcategories|collections|tags|stones|attributes|attribute-values|variant-types)(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS, ADMIN_PERMISSION_MANAGE_INVENTORY, ADMIN_PERMISSION_MANAGE_WEBSITE},
    },
    {
        "pattern": re.compile(r"^/admin/(metal-types|metal-purities|metal-colors|metal-rates)(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_INVENTORY, ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/stores(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_STORES},
    },
    {
        "pattern": re.compile(r"^/admin/dashboard-(summary|trends)(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_REPORTS, ADMIN_PERMISSION_MANAGE_SALES, ADMIN_PERMISSION_VIEW_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/inventory(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_INVENTORY, ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/products(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS, ADMIN_PERMISSION_MANAGE_INVENTORY},
    },
    {
        "pattern": re.compile(r"^/admin/variants(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/images(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    # FIX 4.3: Admin profile routes — any authenticated admin can access their own profile
    {
        "pattern": re.compile(r"^/admin/me(?:/.*)?$"),
        "methods": None,
        "any_of": set(),  # Empty set = any authenticated admin
    },
    {
        "pattern": re.compile(r"^/admin/sales(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_SALES, ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/reports(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_REPORTS},
    },
    # Analytics routes
    {
        "pattern": re.compile(r"^/admin/analytics(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_ANALYTICS},
    },
    {
        "pattern": re.compile(r"^/admin/analytics/refresh-cache$"),
        "methods": {"POST"},
        "any_of": {ADMIN_PERMISSION_MANAGE_STORES},
    },
    # Support ticket routes
    {
        "pattern": re.compile(r"^/admin/tickets(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_TICKETS, ADMIN_PERMISSION_MANAGE_TICKETS},
    },
    {
        "pattern": re.compile(r"^/admin/tickets(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_TICKETS},
    },
    # Campaign routes
    {
        "pattern": re.compile(r"^/admin/campaigns(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_MANAGE_CAMPAIGNS, ADMIN_PERMISSION_VIEW_ANALYTICS},
    },
    {
        "pattern": re.compile(r"^/admin/campaigns(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_CAMPAIGNS},
    },
    # FIX: routes previously missing from ADMIN_ROUTE_PERMISSION_RULES (403'd for everyone, discovered 2026-09-18)
    {
        "pattern": re.compile(r"^/admin/upload-image$"),
        "methods": {"POST"},
        "any_of": {ADMIN_PERMISSION_MANAGE_CMS, ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/legal-pages(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_CMS},
    },
    {
        "pattern": re.compile(r"^/admin/reviews(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_PRODUCTS},
    },
    {
        "pattern": re.compile(r"^/admin/seo(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_CMS},
    },
    {
        "pattern": re.compile(r"^/admin/global-config(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_CMS},
    },
    {
        "pattern": re.compile(r"^/admin/store-locations(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_STORE},
    },
    {
        "pattern": re.compile(r"^/admin/contact-submissions(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_MANAGE_CUSTOMERS},
    },
    {
        "pattern": re.compile(r"^/admin/commission-requests(?:/.*)?$"),
        "methods": {"GET"},
        "any_of": {ADMIN_PERMISSION_VIEW_SALES, ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/commission-requests(?:/.*)?$"),
        "methods": WRITE_METHODS,
        "any_of": {ADMIN_PERMISSION_MANAGE_SALES},
    },
    {
        "pattern": re.compile(r"^/admin/newsletter(?:/.*)?$"),
        "methods": None,
        "any_of": {ADMIN_PERMISSION_VIEW_REPORTS},
    },
    {
        "pattern": re.compile(r"^/admin/search(?:/.*)?$"),
        "methods": None,
        "any_of": set(),  # Empty set = any authenticated admin
    },
]


logger = logging.getLogger(__name__)


def _get_secret() -> str:
    secret = os.getenv("ADMIN_JWT_SECRET")
    if not secret:
        raise ValueError("CRITICAL: ADMIN_JWT_SECRET env var is not set.")
    return secret


def _get_ttl_seconds() -> int:
    raw = (os.getenv("ADMIN_JWT_TTL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_ADMIN_JWT_TTL_SECONDS

    try:
        ttl = int(raw)
    except ValueError:
        return DEFAULT_ADMIN_JWT_TTL_SECONDS

    return ttl if ttl > 0 else DEFAULT_ADMIN_JWT_TTL_SECONDS


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _sign(message: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


# FIX 4.4: Proper email validation regex — replaces weak single '@' check.
# Also blocks internal/local domains that should never be used for admin accounts.
_EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_BLOCKED_EMAIL_DOMAINS = {"localhost", ".local", ".internal", ".test", ".example", ".invalid"}


def normalize_admin_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or not _EMAIL_REGEX.match(normalized):
        raise HTTPException(status_code=400, detail="A valid admin email is required")
    # Block internal/local domains that should not be used for admin accounts
    domain = normalized.split("@", 1)[1]
    if domain in _BLOCKED_EMAIL_DOMAINS or any(domain.endswith(suffix) for suffix in _BLOCKED_EMAIL_DOMAINS):
        raise HTTPException(status_code=400, detail="Admin email must use a public domain (not localhost or .local)")
    return normalized


def normalize_admin_role(role: str) -> str:
    normalized = role.strip().lower().replace(" ", "_")
    normalized = ROLE_ALIASES.get(normalized, normalized)
    if normalized not in ROLE_DESCRIPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed roles: {', '.join(sorted(ROLE_DESCRIPTIONS.keys()))}",
        )
    return normalized


def normalize_admin_permissions(permissions: list[str] | None) -> list[str]:
    if permissions is None:
        return []

    normalized = sorted({value.strip() for value in permissions if isinstance(value, str) and value.strip()})
    invalid = [value for value in normalized if value not in ALL_ADMIN_PERMISSIONS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid permissions: {', '.join(invalid)}")

    return normalized


def check_no_privilege_escalation(creator_role: str, target_role: str) -> None:
    """SECURITY FIX 1.2: Ensure the creator's role level is strictly higher than the role being granted.
    This prevents privilege escalation (e.g., an 'admin' cannot create a 'super_admin')."""
    creator_level = ROLE_HIERARCHY.get(creator_role, 0)
    target_level = ROLE_HIERARCHY.get(target_role, 0)
    if creator_level <= target_level:
        raise HTTPException(
            status_code=403,
            detail=f"Privilege escalation denied: you cannot grant role '{target_role}' (your role level must be strictly higher)",
        )


def resolve_admin_permissions(role: str, permissions: list[str] | None = None) -> list[str]:
    normalize_admin_role(role)
    return normalize_admin_permissions(permissions)


def get_admin_role_by_name(db: Session, role: str) -> AdminRole:
    role_name = normalize_admin_role(role)
    role_row = db.query(AdminRole).filter(AdminRole.name == role_name).first()
    if role_row is None:
        raise HTTPException(status_code=400, detail=f"Role not configured: {role_name}")
    return role_row


def get_admin_user_role(admin_user: AdminUser, db: Session | None = None) -> str:
    if db is not None and admin_user.role_id is not None:
        role_name = (
            db.query(AdminRole.name)
            .filter(AdminRole.id == admin_user.role_id)
            .scalar()
        )
        if isinstance(role_name, str):
            try:
                return normalize_admin_role(role_name)
            except HTTPException:
                pass

    role_value = admin_user.role or "staff"
    try:
        return normalize_admin_role(role_value)
    except HTTPException:
        return "staff"


def _get_role_permissions_for_user(admin_user: AdminUser, db: Session | None = None) -> set[str]:
    role_name = get_admin_user_role(admin_user, db=db)
    default_permissions = set(DEFAULT_ROLE_PERMISSIONS.get(role_name, set()))

    if db is None or admin_user.role_id is None:
        return default_permissions

    rows = (
        db.query(AdminPermission.key)
        .join(AdminRolePermission, AdminRolePermission.permission_id == AdminPermission.id)
        .filter(AdminRolePermission.role_id == admin_user.role_id)
        .all()
    )
    if not rows:
        return default_permissions

    return {row[0] for row in rows if isinstance(row[0], str)}


def get_admin_user_permissions(admin_user: AdminUser, db: Session | None = None) -> list[str]:
    role_permissions = _get_role_permissions_for_user(admin_user, db=db)
    permissions = admin_user.permissions if isinstance(admin_user.permissions, list) else None
    try:
        custom_permissions = set(normalize_admin_permissions(permissions))
        return sorted(role_permissions.union(custom_permissions))
    except HTTPException:
        return sorted(role_permissions)


def list_admin_roles_with_permissions(db: Session | None = None) -> list[dict[str, Any]]:
    if db is None:
        return [
            {
                "role": role_name,
                "role_id": None,
                "label": role_name.replace("_", " ").title(),
                "description": ROLE_DESCRIPTIONS.get(role_name),
                "permissions": sorted(DEFAULT_ROLE_PERMISSIONS[role_name]),
            }
            for role_name in sorted(DEFAULT_ROLE_PERMISSIONS.keys())
        ]

    roles = db.query(AdminRole).order_by(AdminRole.id.asc()).all()
    rows = (
        db.query(AdminRolePermission.role_id, AdminPermission.key)
        .join(AdminPermission, AdminPermission.id == AdminRolePermission.permission_id)
        .all()
    )
    permission_map: dict[int, set[str]] = {}
    for role_id, permission_key in rows:
        if isinstance(permission_key, str):
            permission_map.setdefault(int(role_id), set()).add(permission_key)

    result: list[dict[str, Any]] = []
    for role_row in roles:
        role_name = normalize_admin_role(role_row.name)
        result.append(
            {
                "role": role_name,
                "role_id": role_row.id,
                "label": role_name.replace("_", " ").title(),
                "description": role_row.description,
                "permissions": sorted(permission_map.get(role_row.id, set())),
            }
        )
    return result


def list_admin_permissions_catalog(db: Session | None = None) -> list[dict[str, Any]]:
    if db is None:
        return [
            {
                "key": key,
                "description": ADMIN_PERMISSION_DESCRIPTIONS.get(key),
            }
            for key in ALL_ADMIN_PERMISSIONS
        ]

    permissions = db.query(AdminPermission).order_by(AdminPermission.key.asc()).all()
    return [
        {
            "id": permission.id,
            "key": permission.key,
            "description": permission.description,
        }
        for permission in permissions
    ]


def _normalized_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _resolve_required_permissions(path: str, method: str) -> set[str] | None:
    normalized_path = _normalized_path(path)
    normalized_method = method.upper()

    for rule in ADMIN_ROUTE_PERMISSION_RULES:
        methods = rule.get("methods")
        if methods is not None and normalized_method not in methods:
            continue
        pattern = rule["pattern"]
        if not pattern.match(normalized_path):
            continue
        return set(rule.get("any_of") or set())

    return None


def hash_admin_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")

    normalized = password.strip()
    if len(normalized) < 8:
        raise ValueError("Password must be at least 8 characters")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_admin_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_part, hash_part = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_raw)
        salt = _b64url_decode(salt_part)
        expected_digest = _b64url_decode(hash_part)
    except Exception:
        return False

    candidate_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(candidate_digest, expected_digest)


def create_admin_access_token(
    *,
    admin_user_id: int,
    email: str,
    role: str,
    permissions: list[str] | None = None,
    role_id: int | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(admin_user_id),
        "email": email,
        "role": role,
        "role_id": role_id,
        "permissions": permissions or [],
        "iat": now,
        "exp": now + _get_ttl_seconds(),
    }

    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}"
    signature_part = _sign(signing_input, _get_secret())

    return f"{signing_input}.{signature_part}"


def decode_admin_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid admin token")

    header_part, payload_part, signature_part = parts
    signing_input = f"{header_part}.{payload_part}"
    expected_signature = _sign(signing_input, _get_secret())

    if not secrets.compare_digest(signature_part, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    try:
        payload_raw = _b64url_decode(payload_part)
        payload = json.loads(payload_raw)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid admin token") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    exp = payload.get("exp")
    now = int(time.time())
    if not isinstance(exp, int) or exp <= now:
        raise HTTPException(status_code=401, detail="Admin token expired")

    return payload


def get_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization required")

    return token


def get_admin_token_payload(
    authorization: str | None = Header(default=None, alias="Authorization"),
    admin_token_cookie: str | None = Cookie(default=None, alias=ADMIN_AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    # H6 FIX: prefer the HttpOnly cookie; fall back to a Bearer header for any
    # non-browser caller (scripts, the admin bootstrap CLI's own API calls, etc.)
    token = admin_token_cookie or get_bearer_token(authorization)
    return decode_admin_access_token(token)


def get_current_admin_user(
    request: Request,
    db: Session = Depends(get_db),
    token_payload: dict[str, Any] = Depends(get_admin_token_payload),
) -> AdminUser:
    payload = getattr(request.state, "admin_token_payload", token_payload)
    subject = payload.get("sub")

    if subject is None:
        raise HTTPException(status_code=401, detail="Invalid admin token")

    try:
        user_id = int(subject)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid admin token") from exc

    admin_user = (
        db.query(AdminUser)
        .filter(AdminUser.id == user_id, AdminUser.is_active.is_(True))
        .first()
    )

    if admin_user is None:
        raise HTTPException(status_code=401, detail="Admin user not found or inactive")

    return admin_user


def require_admin_route_permission(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> AdminUser:
    required_any = _resolve_required_permissions(request.url.path, request.method)
    if required_any is None:
        # SECURITY FIX 1.3: Fail-closed — routes not explicitly listed in permission rules are denied.
        # Add the route to ADMIN_ROUTE_PERMISSION_RULES to grant access.
        raise HTTPException(
            status_code=403,
            detail="Access denied: route not in permission rules",
        )
    if not required_any:
        # Empty set means the route is explicitly permitted for all authenticated admins
        return current_admin

    current_permissions = set(get_admin_user_permissions(current_admin, db=db))
    if current_permissions.intersection(required_any):
        return current_admin

    required = ", ".join(sorted(required_any))
    raise HTTPException(status_code=403, detail=f"Insufficient permissions. Requires one of: {required}")


def require_authenticated_admin(_: AdminUser = Depends(get_current_admin_user)) -> None:
    return None


def require_admin_permission(permission: str):
    if permission not in ALL_ADMIN_PERMISSIONS:
        raise ValueError(f"Unsupported permission: {permission}")

    def dependency(
        current_admin: AdminUser = Depends(get_current_admin_user),
        db: Session = Depends(get_db),
    ) -> AdminUser:
        permissions = get_admin_user_permissions(current_admin, db=db)
        if permission not in permissions:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_admin

    return dependency


def require_any_admin_permissions(*permissions: str):
    requested_permissions = [value for value in permissions if value]
    invalid_permissions = [value for value in requested_permissions if value not in ALL_ADMIN_PERMISSIONS]
    if invalid_permissions:
        raise ValueError(f"Unsupported permissions: {', '.join(sorted(set(invalid_permissions)))}")

    def dependency(
        current_admin: AdminUser = Depends(get_current_admin_user),
        db: Session = Depends(get_db),
    ) -> AdminUser:
        user_permissions = set(get_admin_user_permissions(current_admin, db=db))
        if any(permission in user_permissions for permission in requested_permissions):
            return current_admin
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return dependency
