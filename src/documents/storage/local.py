"""
Local filesystem storage implementation.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from typing import Optional

from .base import StorageBackend


class LocalFileStorage(StorageBackend):
    """
    Local filesystem implementation of document storage.
    
    Stores documents as regular files on the local filesystem,
    maintaining directory structure from the keys.
    """

    def __init__(self, base_path: Path):
        """
        Initialize local storage.
        
        Args:
            base_path: Root directory for document storage
        """
        self.base_path = Path(base_path).resolve()

    def _full_path(self, key: str) -> Path:
        """Convert key to full filesystem path."""
        # Reject absolute paths
        if key.startswith("/"):
            raise ValueError(f"Invalid key: {key}")

        full = (self.base_path / key).resolve()

        # Ensure the resolved path is still under base_path
        if not full.is_relative_to(self.base_path):
            raise ValueError(f"Invalid key: {key}")

        return full
    
    def get_full_path(self, key: str) -> Path:
        """
        Get the full filesystem path for a key.
        
        Public method for cases where direct path access is needed
        (e.g., optimization in materialization for local files).
        
        Args:
            key: Storage key
            
        Returns:
            Full filesystem path
        """
        return self._full_path(key)

    def _ensure_parent_dir(self, path: Path) -> None:
        """Create parent directories if needed."""
        path.parent.mkdir(parents=True, exist_ok=True)

    def store(self, key: str, content: BinaryIO, metadata: Optional[dict] = None) -> None:
        """Store document at the given key."""
        path = self._full_path(key)

        # Transparently create parent directories as needed
        self._ensure_parent_dir(path)

        with path.open("wb") as f:
            shutil.copyfileobj(content, f)

        # Metadata could be stored as extended attributes or sidecar file
        # For now, ignoring metadata for local storage

    def retrieve(self, key: str) -> BinaryIO:
        """Retrieve document as stream."""
        path = self._full_path(key)
        if not path.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        return path.open("rb")

    def exists(self, key: str) -> bool:
        """Check if document exists."""
        return self._full_path(key).exists()

    def delete(self, key: str) -> None:
        """
        Delete document and clean up empty directories.
        
        Idempotent - succeeds even if key doesn't exist.
        """
        path = self._full_path(key)
        if path.exists():
            path.unlink()

            # Transparently clean up empty parent directories
            # (this is filesystem-specific behavior)
            self._cleanup_empty_dirs(path.parent)

    def _cleanup_empty_dirs(self, directory: Path) -> None:
        """Remove empty directories up to category root (originals/archive/thumbnails)."""
        from django.conf import settings

        # Determine the root to stop at
        category_roots = [
            settings.ORIGINALS_DIR,
            settings.ARCHIVE_DIR,
            settings.THUMBNAIL_DIR,
        ]

        # Find which category root this path belongs to
        stop_at = self.base_path
        for root in category_roots:
            if directory.is_relative_to(root):
                stop_at = root
                break

        # Clean up empty directories up to the category root
        while directory != stop_at and directory.is_relative_to(stop_at):
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
                else:
                    break
            except OSError:
                break
            directory = directory.parent

    def rename(self, old_key: str, new_key: str) -> None:
        """
        Rename document by changing its key.
        
        Implemented as copy+delete for S3 compatibility.
        Overwrites destination if it exists (matching shutil.move).
        """
        old_path = self._full_path(old_key)
        new_path = self._full_path(new_key)

        if not old_path.exists():
            raise FileNotFoundError(f"Key not found: {old_key}")

        # Transparently create parent directories for new location
        self._ensure_parent_dir(new_path)

        # Delete destination if it exists (for consistent overwrite semantics with S3)
        if new_path.exists():
            new_path.unlink()

        # Copy then delete (S3-compatible semantics)
        shutil.copy2(old_path, new_path)
        old_path.unlink()

        # Transparently clean up empty directories from old location
        self._cleanup_empty_dirs(old_path.parent)

    def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        search_path = self._full_path(prefix) if prefix else self.base_path

        if not search_path.exists():
            return []

        keys = []
        if search_path.is_dir():
            # List all files recursively, skipping symlinks
            for item in search_path.rglob("*"):
                try:
                    # Skip symlinks for security
                    if item.is_symlink():
                        continue
                    if item.is_file():
                        rel_path = item.relative_to(self.base_path)
                        # Always use forward slashes regardless of OS
                        key = rel_path.as_posix()
                        keys.append(key)
                except OSError:
                    # Skip files we can't access
                    continue
        elif search_path.is_file() and not search_path.is_symlink():
            # Single file (not a symlink)
            rel_path = search_path.relative_to(self.base_path)
            key = rel_path.as_posix()
            keys.append(key)

        return sorted(keys)

    def modified_time(self, key: str) -> datetime:
        """Retrieve document as stream."""
        path = self._full_path(key)
        if not path.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    def size(self, key: str) -> int:
        """Get file size in bytes from the local filesystem."""
        path = self._full_path(key)
        if not path.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        return path.stat().st_size
    
    def move_to_trash(self, key: str, trash_filename: str) -> None:
        """
        Move file to trash directory for permanent deletion.
        
        For local storage, moves to EMPTY_TRASH_DIR.
        """
        from django.conf import settings
        
        if settings.EMPTY_TRASH_DIR is None:
            raise ValueError("EMPTY_TRASH_DIR is not configured")
        
        source_path = self._full_path(key)
        if not source_path.exists():
            return  # Already gone
        
        trash_path = Path(trash_filename)
        
        # Handle filename conflicts
        counter = 0
        while True:
            if counter == 0:
                new_file_path = settings.EMPTY_TRASH_DIR / trash_filename
            else:
                new_file_path = settings.EMPTY_TRASH_DIR / f"{trash_path.stem}_{counter:02d}{trash_path.suffix}"
            
            if not new_file_path.exists():
                break
            counter += 1
        
        # Move to trash
        shutil.move(str(source_path), str(new_file_path))
        
        # Clean up empty directories
        self._cleanup_empty_dirs(source_path.parent)