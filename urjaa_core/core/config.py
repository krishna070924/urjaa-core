import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
	app_name: str = os.getenv("APP_NAME", "Urjaa Ornaments API")
	app_version: str = os.getenv("APP_VERSION", "1.0.0")
	debug: bool = os.getenv("DEBUG", "false").lower() == "true"
	cloudinary_cloud_name: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
	cloudinary_api_key: str = os.getenv("CLOUDINARY_API_KEY", "")
	cloudinary_api_secret: str = os.getenv("CLOUDINARY_API_SECRET", "")
	# L-05: storage backend selection (D32 — local disk for now, CDN later).
	storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
	media_root: str = os.getenv("MEDIA_ROOT", "/app/media")
	media_base_url: str = os.getenv("MEDIA_BASE_URL", "http://localhost:8000/media")
	razorpay_key_id: str = os.getenv("RAZORPAY_KEY_ID", "")
	razorpay_key_secret: str = os.getenv("RAZORPAY_KEY_SECRET", "")
	razorpay_webhook_secret: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")


settings = Settings()
