from urjaa_core.core.config import settings
from urjaa_core.services.payment_service import RazorpayService
from urjaa_core.services.storage_service import CloudinaryStorageService, LocalStorageService, StorageService


def get_storage_service() -> StorageService:
    # D32: local disk is the default; set STORAGE_BACKEND=cloudinary to opt in.
    if settings.storage_backend == "cloudinary":
        return CloudinaryStorageService()
    return LocalStorageService()


def get_payment_service() -> RazorpayService:
    return RazorpayService()
