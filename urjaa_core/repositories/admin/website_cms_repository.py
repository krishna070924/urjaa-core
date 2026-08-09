from sqlalchemy.orm import Session

from urjaa_core.models.website_config import WebsiteConfig


class WebsiteCMSRepository:
    @staticmethod
    def fetch_by_key(db: Session, key: str) -> WebsiteConfig | None:
        return db.query(WebsiteConfig).filter(WebsiteConfig.key == key).first()

    @staticmethod
    def upsert_by_key(db: Session, key: str, value: dict) -> WebsiteConfig:
        config = WebsiteCMSRepository.fetch_by_key(db, key)
        if config is None:
            config = WebsiteConfig(key=key, value=value)
            db.add(config)
        else:
            config.value = value

        db.flush()
        db.refresh(config)
        return config
