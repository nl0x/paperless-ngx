"""
Storage manager singleton for document storage backend.
"""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from typing import Optional

from .base import StorageBackend
from .local import LocalFileStorage

_storage_backend: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """
    Get the configured storage backend (singleton).
    
    Returns:
        Configured StorageBackend instance
    """
    global _storage_backend

    if _storage_backend is None:
        _storage_backend = _create_storage_backend()

    return _storage_backend


def _create_storage_backend() -> StorageBackend:
    """
    Create storage backend from settings.
    
    Returns:
        Configured StorageBackend instance
    """
    # Get backend type from settings (default to local)
    backend_type = getattr(settings, "PAPERLESS_STORAGE_BACKEND", "local").lower()

    if backend_type == "local":
        # Local filesystem storage
        media_root = Path(settings.MEDIA_ROOT)
        return LocalFileStorage(media_root)
    elif backend_type == "s3":
        # S3 storage
        from .s3 import S3Storage
        return S3Storage()
    else:
        raise ImproperlyConfigured(
            f"Unknown storage backend: {backend_type}. "
            f"Valid options are: 'local', 's3'",
        )


def reset_storage_backend() -> None:
    """
    Reset the storage backend singleton (mainly for testing).
    """
    global _storage_backend
    _storage_backend = None
