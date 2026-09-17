from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from urjaa_core.core.database import get_db
from urjaa_core.models.store import Store


def get_store_id(
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
) -> UUID:
    if not x_store_id:
        raise HTTPException(status_code=400, detail="Store ID required")

    try:
        parsed_store_id = UUID(x_store_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid store ID")

    store = db.query(Store).filter(Store.id == parsed_store_id).first()
    if not store:
        raise HTTPException(status_code=400, detail="Invalid store ID")

    return parsed_store_id


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
