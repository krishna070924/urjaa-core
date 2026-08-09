from sqlalchemy.orm import Session
from urjaa_core.repositories import collection_repository


def list_collections(db: Session):
    return collection_repository.get_all_collections(db)


def get_collection(db: Session, slug: str):
    return collection_repository.get_collection_by_slug(db, slug)