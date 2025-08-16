"""
Base storage interface for document storage backends.
"""

from abc import ABC
from abc import abstractmethod
from datetime import datetime
from typing import BinaryIO
from typing import Optional


class StorageBackend(ABC):
    """
    Minimal document storage interface - a key-value store abstraction.
    
    This treats storage as a key-value store, which maps naturally to:
    - Local filesystem: key = relative file path from MEDIA_ROOT
    - S3: key = object key with prefix
    - Other cloud storage: key = blob name
    
    Contract:
    - Keys are always relative paths (e.g., "documents/originals/2024/doc.pdf")
    - Keys use forward slashes regardless of OS
    - Empty directories don't need to exist (S3 has no real directories)
    - delete() is idempotent (no error if key doesn't exist)
    - rename() overwrites destination if it exists (like shutil.move)
    - All operations should be atomic where possible
    """

    @abstractmethod
    def store(self, key: str, content: BinaryIO, metadata: Optional[dict] = None) -> None:
        """
        Store document with optional metadata.
        
        Args:
            key: Storage key (relative path)
            content: File-like object to store
            metadata: Optional metadata dictionary
        """

    @abstractmethod
    def retrieve(self, key: str) -> BinaryIO:
        """
        Retrieve document as stream.
        
        Args:
            key: Storage key (relative path)
            
        Returns:
            File-like object for reading
            
        Raises:
            FileNotFoundError: If key doesn't exist
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if document exists.
        
        Args:
            key: Storage key (relative path)
            
        Returns:
            True if document exists, False otherwise
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete document.
        
        Args:
            key: Storage key (relative path)
            
        Note:
            Idempotent - succeeds even if key doesn't exist
        """

    @abstractmethod
    def rename(self, old_key: str, new_key: str) -> None:
        """
        Rename document (change its key).
        
        Args:
            old_key: Current storage key
            new_key: New storage key
            
        Raises:
            FileNotFoundError: If old_key doesn't exist
        """

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """
        List all keys with given prefix.
        
        Args:
            prefix: Key prefix to filter by (e.g., "2024/01/")
            
        Returns:
            List of matching keys
        """

    @abstractmethod
    def modified_time(self, key: str) -> datetime:
        """
        Get the last content-modified timestamp for a single object.

        Args:
            key: Storage key of the object.

        Returns:
            A timezone-aware UTC datetime of the last modification.

        Raises:
            FileNotFoundError: If the key doesn't exist.
        """

    @abstractmethod
    def size(self, key: str) -> int:
        """
        Get the size of the object in bytes.

        Args:
            key: Storage key of the object.

        Returns:
            Size in bytes.

        Raises:
            FileNotFoundError: If the key doesn't exist.
        """
    
    @abstractmethod
    def move_to_trash(self, key: str, trash_filename: str) -> None:
        """
        Move file to trash location for permanent deletion.
        
        Args:
            key: Storage key of the file to move
            trash_filename: Desired filename in the trash location
        
        Note:
            Implementation depends on storage backend and EMPTY_TRASH_DIR setting
        """