"""
AWS S3 storage implementation.
"""

import logging
import os
from datetime import datetime, timezone
from typing import BinaryIO
from typing import Optional

from .base import StorageBackend

logger = logging.getLogger(__name__)


class S3Storage(StorageBackend):
    """
    AWS S3 implementation of document storage.
    
    Stores documents as objects in an S3 bucket, with optional
    prefix to organize within the bucket.
    """

    def __init__(self):
        """
        Initialize S3 storage from environment variables.
        
        Environment variables:
            PAPERLESS_S3_BUCKET: S3 bucket name (required)
            PAPERLESS_S3_REGION: AWS region (default: us-east-1)
            PAPERLESS_S3_ENDPOINT: Custom endpoint URL (for MinIO, etc.)
            PAPERLESS_S3_ACCESS_KEY: AWS access key ID (optional)
            PAPERLESS_S3_SECRET_KEY: AWS secret access key (optional)
        """
        import boto3
        from botocore.exceptions import ClientError
        from botocore.exceptions import NoCredentialsError

        # Store ClientError for use in other methods
        self.ClientError = ClientError

        # Required settings
        self.bucket_name = os.getenv("PAPERLESS_S3_BUCKET")
        if not self.bucket_name:
            raise ValueError("PAPERLESS_S3_BUCKET is required for S3 storage")

        # Optional settings
        self.region = os.getenv("PAPERLESS_S3_REGION", "us-east-1")
        self.endpoint_url = os.getenv("PAPERLESS_S3_ENDPOINT")  # For MinIO/alternatives
        self.access_key = os.getenv("PAPERLESS_S3_ACCESS_KEY")
        self.secret_key = os.getenv("PAPERLESS_S3_SECRET_KEY")

        # Initialize S3 client - will use AWS credentials from environment/IAM role
        try:
            from botocore.config import Config

            # Configure for path-style URLs if needed (MinIO, etc)
            config = None
            if self.endpoint_url:  # Only use path-style for custom endpoints
                config = Config(s3={"addressing_style": "path"})

            # Build client kwargs
            client_kwargs = {
                "region_name": self.region,
                "endpoint_url": self.endpoint_url,
                "config": config,
            }
            
            # Add credentials if provided
            if self.access_key and self.secret_key:
                client_kwargs["aws_access_key_id"] = self.access_key
                client_kwargs["aws_secret_access_key"] = self.secret_key

            self.s3_client = boto3.client("s3", **client_kwargs)
            # Test connection
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Connected to S3 bucket: {self.bucket_name}")
        except (NoCredentialsError, ClientError) as e:
            raise ValueError(f"Failed to connect to S3: {e}")

    def _full_key(self, key: str) -> str:
        """Convert relative key to full S3 key."""
        return key.lstrip("/")

    def store(self, key: str, content: BinaryIO, metadata: Optional[dict] = None) -> None:
        """Store document in S3."""
        full_key = self._full_key(key)

        extra_args = {}

        if metadata:
            # Handle Content-Type specially
            if "content_type" in metadata:
                extra_args["ContentType"] = metadata["content_type"]

            # Store other metadata as S3 object metadata
            s3_metadata = {}
            for k, v in metadata.items():
                if k != "content_type":  # Skip content_type as it's handled above
                    s3_metadata[k] = str(v)

            if s3_metadata:
                extra_args["Metadata"] = s3_metadata

        try:
            self.s3_client.upload_fileobj(
                content,
                self.bucket_name,
                full_key,
                ExtraArgs=extra_args if extra_args else None,
            )
            logger.debug(f"Stored {key} to S3")
        except Exception as e:
            logger.error(f"Failed to store {key}: {e}")
            raise

    def retrieve(self, key: str) -> BinaryIO:
        """Retrieve document from S3 as stream."""
        full_key = self._full_key(key)

        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=full_key,
            )
            return response["Body"]
        except self.ClientError as e:
            # Check the error code
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(f"Key not found: {key}") from e
            # Re-raise other client errors
            raise

    def exists(self, key: str) -> bool:
        """Check if document exists in S3."""
        full_key = self._full_key(key)

        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=full_key,
            )
            return True
        except self.ClientError:
            # Any ClientError (404, 403, etc.) means the object doesn't exist
            # or we can't access it, so return False
            return False

    def delete(self, key: str) -> None:
        """Delete document from S3."""
        full_key = self._full_key(key)
        self.s3_client.delete_object(
            Bucket=self.bucket_name,
            Key=full_key,
        )

    def rename(self, old_key: str, new_key: str) -> None:
        """Rename document in S3 (copy and delete)."""
        old_full_key = self._full_key(old_key)
        new_full_key = self._full_key(new_key)

        # Check if source exists
        if not self.exists(old_key):
            raise FileNotFoundError(f"Key not found: {old_key}")

        # Copy to new location
        copy_source = {
            "Bucket": self.bucket_name,
            "Key": old_full_key,
        }
        self.s3_client.copy_object(
            CopySource=copy_source,
            Bucket=self.bucket_name,
            Key=new_full_key,
        )

        # Delete old location
        self.s3_client.delete_object(
            Bucket=self.bucket_name,
            Key=old_full_key,
        )

    def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys with given prefix."""
        full_prefix = self._full_key(prefix)

        paginator = self.s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=self.bucket_name,
            Prefix=full_prefix,
        )

        keys = []
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    keys.append(obj["Key"])

        return sorted(keys)

    def modified_time(self, key: str) -> datetime:
        """Return the S3 object's last-modified time (UTC, tz-aware)."""
        full_key = self._full_key(key)
        try:
            # HEAD is cheaper than GET and returns metadata incl. LastModified
            resp = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=full_key,
            )
        except self.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(f"Key not found: {key}") from e
            raise

        lm = resp["LastModified"] # boto3 returns a tz-aware UTC datetime
        # Normalize explicitly to UTC tzinfo object
        return lm if lm.tzinfo else lm.replace(tzinfo=timezone.utc)

    def size(self, key: str) -> int:
        """Get object size in bytes from S3."""
        full_key = self._full_key(key)
        try:
            # HEAD is cheap and returns metadata, including ContentLength
            resp = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=full_key,
            )
            return int(resp["ContentLength"])
        except self.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(f"Key not found: {key}") from e
            raise
    
    def move_to_trash(self, key: str, trash_filename: str) -> None:
        """
        Move file to trash prefix for permanent deletion.
        
        For S3, uses EMPTY_TRASH_DIR as a key prefix.
        """
        from django.conf import settings
        from pathlib import Path
        
        if settings.EMPTY_TRASH_DIR is None:
            raise ValueError("EMPTY_TRASH_DIR is not configured")
        
        # Use EMPTY_TRASH_DIR as prefix, stripping leading slash
        trash_prefix = str(settings.EMPTY_TRASH_DIR).lstrip('/')
        trash_path = Path(trash_filename)
        
        # Find a non-existing trash key
        counter = 0
        while True:
            if counter == 0:
                new_trash_key = f"{trash_prefix}/{trash_filename}"
            else:
                new_trash_key = f"{trash_prefix}/{trash_path.stem}_{counter:02d}{trash_path.suffix}"
            
            # Check if target exists
            if not self.exists(new_trash_key):
                # Target doesn't exist, safe to move
                self.rename(key, new_trash_key)
                break
            
            counter += 1