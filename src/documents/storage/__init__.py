"""
Document storage abstraction for Paperless-ngx.

This package provides a unified interface for storing documents
across different backends (local filesystem, S3, etc.).
"""

from .base import StorageBackend
from .local import LocalFileStorage
from .manager import get_storage_backend
from .manager import reset_storage_backend
from .s3 import S3Storage

__all__ = [
    "LocalFileStorage",
    "S3Storage",
    "StorageBackend",
    "get_storage_backend",
    "reset_storage_backend",
]
