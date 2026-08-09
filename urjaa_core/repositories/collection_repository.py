from sqlalchemy.orm import Session
from urjaa_core.models.collection import Collection


def get_all_collections(db: Session):
    return db.query(Collection).order_by(Collection.display_order).all()


def get_collection_by_slug(db: Session, slug: str):
    return db.query(Collection).filter(Collection.slug == slug).first()