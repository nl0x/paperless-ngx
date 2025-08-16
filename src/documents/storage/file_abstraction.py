"""
File abstraction for document files (source, archive, thumbnail).

This module provides a thin wrapper around storage backend operations
with a storage key, avoiding the need to pass keys everywhere.
"""

from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from typing import BinaryIO, Optional, Union

from documents.storage import get_storage_backend
from documents.storage.materialize import materialize_to_temp


class DocumentFile:
    """
    Thin wrapper that binds a storage key to storage operations.
    
    This class simply delegates to the storage backend, but eliminates
    the need to pass the storage key to every operation.
    """
    
    def __init__(self, storage_key: str, is_encrypted=False):
        """
        Initialize a DocumentFile.
        
        Args:
            storage_key: The storage backend key (e.g., "documents/originals/00001.pdf")
        """
        self.key = storage_key
        self._storage = get_storage_backend()
        # Automatically detect GPG encryption from the key
        self.is_gpg_encrypted = is_encrypted
    
    def _maybe_decrypt(self, fh: BinaryIO) -> BinaryIO:
        """Decrypt file handle if this file is GPG encrypted."""
        if self.is_gpg_encrypted:
            from paperless.db import GnuPG
            data = fh.read()
            if hasattr(fh, "close"):
                fh.close()
            return BytesIO(GnuPG.decrypted(data))
        return fh
    
    # Delegate all operations to storage backend with our key
    @property
    def exists(self) -> bool:
        return self._storage.exists(self.key)
    
    @property
    def size(self) -> int:
        return self._storage.size(self.key)
    
    @property
    def modified_time(self) -> datetime:
        return self._storage.modified_time(self.key)
    
    def open(self, mode: str = 'rb') -> BinaryIO:
        """
        Open file for reading, with automatic GPG decryption if needed.
        
        Args:
            mode: File mode (must include 'r')
            decrypt: Whether to decrypt if file is GPG encrypted (default: True)
        """
        if 'r' in mode:
            fh = self._storage.retrieve(self.key)
            return self._maybe_decrypt(fh)

        raise ValueError("Use write() method for writing")
    
    def read(self) -> bytes:
        with self.open('rb') as f:
            return f.read()
    
    def write(self, content: Union[bytes, BinaryIO]) -> None:
        if isinstance(content, bytes):
            from io import BytesIO
            content = BytesIO(content)
        self._storage.store(self.key, content)
    
    @contextmanager
    def materialize(self, suffix: Optional[str] = None):
        """Get temporary local file path when needed."""
        # Always decrypt if file is GPG encrypted
        with materialize_to_temp(self.key, suffix=suffix, decrypt_gpg=self.is_gpg_encrypted) as path:
            yield path
    
    def delete(self) -> None:
        self._storage.delete(self.key)
    
    def rename(self, new_key: str) -> str:
        """
        Rename/move this file to a new storage key.
        
        Args:
            new_key: The new storage key to move the file to
            
        Returns:
            The old key (for rollback if needed)
        """
        old_key = self.key
        if self.exists:
            self._storage.rename(self.key, new_key)
            self.key = new_key  # Update our key to the new location
        return old_key
    
    def move_to_trash(self, trash_filename: str) -> None:
        """
        Move file to trash location for permanent deletion.
        
        Delegates to storage backend's move_to_trash implementation.
        
        Args:
            trash_filename: The desired filename in the trash location
        """
        self._storage.move_to_trash(self.key, trash_filename)
