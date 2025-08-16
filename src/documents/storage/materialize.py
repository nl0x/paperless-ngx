"""
Utility for materializing storage files to local filesystem temporarily.

This enables tools that require local file access (OCR, ImageMagick, etc.)
to work with files stored in S3 or other remote backends.
"""

import io
import logging
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from documents.storage import get_storage_backend

logger = logging.getLogger("paperless.storage.materialize")


@contextmanager
def materialize_to_temp(key: str, suffix: str = None, decrypt_gpg: bool = False) -> Generator[Path, None, None]:
    """
    Materialize a file from storage to a temporary local path.
    
    Downloads the file from storage to a unique temp directory,
    optionally decrypts GPG files, yields the local path, then cleans up when done.
    
    For local storage without GPG encryption, this returns the actual file path
    without copying for better performance.
    
    Args:
        key: Storage key to materialize
        suffix: Optional file suffix for the temp file
        decrypt_gpg: If True, decrypt GPG-encrypted files
    
    Yields:
        Path to the temporary local file (decrypted if GPG)
    
    Example:
        with materialize_to_temp("documents/originals/doc.pdf.gpg", decrypt_gpg=True) as local_path:
            # local_path contains decrypted content for OCR
            run_ocr(local_path)
    """
    storage = get_storage_backend()
    
    # Optimization: For local storage without encryption, return the actual path
    if storage.__class__.__name__ == "LocalFileStorage" and not decrypt_gpg:
        # For local files, just return the actual path - no need to copy
        actual_path = storage.get_full_path(key)
        logger.debug(f"Using direct path for local file: {actual_path}")
        yield actual_path
        return

    # For S3 or encrypted files, create a temporary copy
    with tempfile.TemporaryDirectory(prefix="paperless-materialize-") as temp_dir:
        temp_dir_path = Path(temp_dir)

        # Generate filename from key, preserving extension
        key_path = Path(key)
        temp_filename = key_path.name

        # If decrypting GPG, remove .gpg extension for the temp file
        if decrypt_gpg and temp_filename.endswith(".gpg"):
            temp_filename = temp_filename[:-4]  # Remove .gpg

        if suffix and not temp_filename.endswith(suffix):
            temp_filename += suffix

        temp_file_path = temp_dir_path / temp_filename

        try:
            # Download from storage to temp file
            logger.debug(f"Materializing {key} to {temp_file_path} (decrypt={decrypt_gpg})")
            file_handle = storage.retrieve(key)

            # Handle GPG decryption if needed
            if decrypt_gpg:
                from paperless.db import GnuPG
                # Read all data first - GnuPG.decrypted expects bytes
                data = file_handle.read() if hasattr(file_handle, "read") else file_handle
                if hasattr(file_handle, "close"):
                    file_handle.close()
                # Decrypt the data
                decrypted_data = GnuPG.decrypted(data)
                file_handle = io.BytesIO(decrypted_data)

            # Write to temp file
            with temp_file_path.open("wb") as f:
                # Handle both file-like objects and boto3 streaming bodies
                if hasattr(file_handle, "read"):
                    # Read in chunks to handle large files
                    chunk_size = 1024 * 1024  # 1MB chunks
                    while True:
                        chunk = file_handle.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                else:
                    # Assume it's bytes
                    f.write(file_handle)

            # Close the storage handle if it has a close method
            if hasattr(file_handle, "close"):
                file_handle.close()

            logger.debug(f"Materialized {key} ({temp_file_path.stat().st_size} bytes)")

            # Yield the path for use
            yield temp_file_path

        except FileNotFoundError:
            logger.error(f"File not found in storage: {key}")
            raise
        except Exception as e:
            logger.error(f"Error materializing {key}: {e}")
            raise
        finally:
            # Cleanup happens automatically when context exits
            logger.debug(f"Cleaned up materialized file: {temp_file_path}")


def store_from_path(key: str, source_path: str | Path, overwrite: bool = True) -> None:
    """
    Store a local file to storage.
    
    Args:
        key: Storage key to store to
        source_path: Local file path to store
        overwrite: If True, use atomic overwrite pattern (store to temp, then rename)
    """
    storage = get_storage_backend()
    source_path = Path(source_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    if overwrite and storage.exists(key):
        # Use atomic overwrite pattern: store to temp key, then rename
        temp_key = f"{key}.tmp.{uuid.uuid4().hex[:8]}"

        try:
            # Store to temporary key
            logger.debug(f"Storing to temp key: {temp_key}")
            with source_path.open("rb") as f:
                storage.store(temp_key, f)

            # Atomic rename (on S3, this is copy + delete)
            logger.debug(f"Renaming {temp_key} to {key}")
            storage.rename(temp_key, key)

        except Exception:
            # Try to clean up temp file on error
            try:
                storage.delete(temp_key)
            except:
                pass
            raise
    else:
        # Direct store
        with source_path.open("rb") as f:
            storage.store(key, f)
