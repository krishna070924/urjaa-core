from uuid import UUID

from fastapi import Depends, Header, HTTPException
from fastapi import Request
from sqlalchemy.orm import Session
import logging

from urjaa_core.core.database import get_db
from urjaa_core.models.store import Store


logger = logging.getLogger(__name__)

# Transitional flag for safe rollout. Set to False to remove GET fallback later.
ALLOW_READ_FALLBACK = True


def _is_public_get_fallback_allowed(request: Request | None) -> bool:
    if not ALLOW_READ_FALLBACK or request is None:
        return False

    method = (request.method or "").upper()
    path = request.url.path if request.url else ""

    if method != "GET":
        return False

    return path == "/products" or path.startswith("/products/") or path.startswith("/public/")


def get_store_id(
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    request: Request = None,
) -> UUID:
    fallback_allowed = _is_public_get_fallback_allowed(request)
    request_method = request.method if request else ""
    request_path = request.url.path if request and request.url else ""

    if not x_store_id:
        if not fallback_allowed:
            raise HTTPException(status_code=400, detail="Store ID required")

        default_store = db.query(Store).order_by(Store.created_at.asc(), Store.id.asc()).first()
        if not default_store:
            raise HTTPException(status_code=400, detail="Store ID required")

        logger.warning("Store ID missing for %s %s — using default store", request_method, request_path)
        return default_store.id

    try:
        parsed_store_id = UUID(x_store_id)
    except ValueError:
        if not fallback_allowed:
            raise HTTPException(status_code=400, detail="Invalid store ID")

        default_store = db.query(Store).order_by(Store.created_at.asc(), Store.id.asc()).first()
        if not default_store:
            raise HTTPException(status_code=400, detail="Invalid store ID")

        logger.warning("Invalid store ID header for %s %s — using default store", request_method, request_path)
        return default_store.id

    store = db.query(Store).filter(Store.id == parsed_store_id).first()
    if store:
        return parsed_store_id

    if not fallback_allowed:
        raise HTTPException(status_code=400, detail="Invalid store ID")

    default_store = db.query(Store).order_by(Store.created_at.asc(), Store.id.asc()).first()
    if not default_store:
        raise HTTPException(status_code=400, detail="Invalid store ID")

    logger.warning("Store ID not found for %s %s — using default store", request_method, request_path)

    return default_store.id


def get_optional_store_id(
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
) -> UUID | None:
    if not x_store_id:
        return None

    try:
        parsed_store_id = UUID(x_store_id)
    except ValueError:
        return None

    store = db.query(Store).filter(Store.id == parsed_store_id).first()
    if not store:
        return None

    return parsed_store_id
