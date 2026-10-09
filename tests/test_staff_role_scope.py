"""Review 9: staff role = Sales + Catalogue + Inventory; catalogue setup
(categories, stones, metals, rates) needs manage_catalog_setup.

Run: .venv/bin/python tests/test_staff_role_scope.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urjaa")

from urjaa_core.core.admin_auth import DEFAULT_ROLE_PERMISSIONS, _resolve_required_permissions


def allowed(role: str, path: str, method: str) -> bool:
    required = _resolve_required_permissions(path, method)
    if required is not None and not required:
        return True  # explicitly open to every signed-in admin
    return required is not None and bool(set(required) & DEFAULT_ROLE_PERMISSIONS[role])


def main() -> None:
    for path, method in [("/admin/products", "POST"), ("/admin/sales/bulk", "POST"), ("/admin/custom-orders", "POST"),
                         ("/admin/categories", "GET"), ("/admin/metal-rates", "GET"),
                         ("/admin/stores/bootstrap", "GET"), ("/admin/stores", "GET")]:
        assert allowed("staff", path, method), (path, method)
    for path, method in [("/admin/categories", "POST"), ("/admin/metal-rates", "POST"), ("/admin/stones/1", "DELETE"),
                         ("/admin/users", "GET"), ("/admin/cms/home", "PUT"),
                         ("/admin/stores", "POST"), ("/admin/stores/abc", "GET")]:
        assert not allowed("staff", path, method), (path, method)
        assert allowed("super_admin", path, method), (path, method)
    assert allowed("manager", "/admin/metal-rates", "POST") and allowed("admin", "/admin/categories", "POST")
    print("staff role scope: sales/products allowed, setup/users/cms denied  OK")


if __name__ == "__main__":
    main()
