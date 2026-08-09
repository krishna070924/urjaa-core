from urjaa_core.services.payment_service import RazorpayService
from urjaa_core.services.storage_service import CloudinaryStorageService, StorageService


def get_storage_service() -> StorageService:
    return CloudinaryStorageService()


def get_payment_service() -> RazorpayService:
    return RazorpayService()
