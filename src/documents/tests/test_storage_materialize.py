"""
Tests for storage materializer utility.
"""

import io
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from documents.storage.base import StorageBackend
from documents.storage.materialize import materialize_to_temp, store_from_path


class MockS3Storage(StorageBackend):
    """Mock S3 storage for testing."""
    
    def __init__(self):
        self.files = {}  # In-memory storage
        self.file_metadata = {}  # Store metadata for files
    
    def store(self, key: str, content, metadata=None):
        # Read content into memory
        if hasattr(content, 'read'):
            data = content.read()
        else:
            data = content
        self.files[key] = data
        # Store metadata including modified time
        from datetime import datetime
        self.file_metadata[key] = {
            'size': len(data),
            'modified': datetime.now(),
            'metadata': metadata or {}
        }
    
    def retrieve(self, key: str):
        if key not in self.files:
            raise FileNotFoundError(f"Key not found: {key}")
        return io.BytesIO(self.files[key])
    
    def exists(self, key: str) -> bool:
        return key in self.files
    
    def delete(self, key: str):
        self.files.pop(key, None)
        self.file_metadata.pop(key, None)
    
    def rename(self, old_key: str, new_key: str):
        if old_key not in self.files:
            raise FileNotFoundError(f"Key not found: {old_key}")
        self.files[new_key] = self.files.pop(old_key)
        self.file_metadata[new_key] = self.file_metadata.pop(old_key)
    
    def list_keys(self, prefix: str = ""):
        return sorted([k for k in self.files.keys() if k.startswith(prefix)])
    
    def size(self, key: str) -> int:
        """Get file size."""
        if key not in self.file_metadata:
            raise FileNotFoundError(f"Key not found: {key}")
        return self.file_metadata[key]['size']
    
    def modified_time(self, key: str):
        """Get last modified time."""
        if key not in self.file_metadata:
            raise FileNotFoundError(f"Key not found: {key}")
        return self.file_metadata[key]['modified']
    
    def move_to_trash(self, key: str, trash_filename: str):
        """Move file to trash."""
        if key not in self.files:
            raise FileNotFoundError(f"Key not found: {key}")
        # For testing, just move to a trash prefix
        trash_key = f"trash/{trash_filename}"
        self.files[trash_key] = self.files.pop(key)
        self.file_metadata[trash_key] = self.file_metadata.pop(key)


class MaterializeTest(TestCase):
    """Test materializer functionality."""
    
    def test_materialize_from_storage(self):
        """Test materializing a file from storage to temp."""
        # Setup mock storage
        mock_storage = MockS3Storage()
        test_content = b"Test document content"
        test_key = "documents/originals/test.pdf"
        mock_storage.store(test_key, test_content)
        
        with mock.patch('documents.storage.materialize.get_storage_backend', return_value=mock_storage):
            # Materialize the file
            with materialize_to_temp(test_key) as local_path:
                # Verify it's a real file
                self.assertTrue(local_path.exists())
                self.assertTrue(local_path.is_file())
                
                # Verify content matches
                with local_path.open("rb") as f:
                    self.assertEqual(f.read(), test_content)
                
                # Verify filename is preserved
                self.assertEqual(local_path.name, "test.pdf")
            
            # Verify cleanup - file should be gone
            self.assertFalse(local_path.exists())
    
    def test_materialize_with_suffix(self):
        """Test materializing with custom suffix."""
        mock_storage = MockS3Storage()
        test_content = b"Test content"
        test_key = "documents/originals/doc"
        mock_storage.store(test_key, test_content)
        
        with mock.patch('documents.storage.materialize.get_storage_backend', return_value=mock_storage):
            with materialize_to_temp(test_key, suffix=".pdf") as local_path:
                self.assertTrue(local_path.name.endswith(".pdf"))
    
    def test_materialize_missing_file(self):
        """Test materializing a non-existent file raises error."""
        mock_storage = MockS3Storage()
        
        with mock.patch('documents.storage.materialize.get_storage_backend', return_value=mock_storage):
            with self.assertRaises(FileNotFoundError):
                with materialize_to_temp("does/not/exist.pdf"):
                    pass
    
    def test_store_from_path(self):
        """Test storing a local file to storage."""
        mock_storage = MockS3Storage()
        
        # Create a temp file to store
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"Store this content")
            tmp_path = Path(tmp.name)
        
        try:
            with mock.patch('documents.storage.materialize.get_storage_backend', return_value=mock_storage):
                # Store the file
                store_from_path("documents/test.txt", tmp_path, overwrite=False)
                
                # Verify it's in storage
                self.assertTrue(mock_storage.exists("documents/test.txt"))
                self.assertEqual(
                    mock_storage.files["documents/test.txt"],
                    b"Store this content"
                )
        finally:
            tmp_path.unlink()
    
    def test_store_with_overwrite(self):
        """Test atomic overwrite pattern."""
        mock_storage = MockS3Storage()
        
        # Store initial content
        mock_storage.store("documents/test.txt", b"Old content")
        
        # Create new content to overwrite with
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"New content")
            tmp_path = Path(tmp.name)
        
        try:
            with mock.patch('documents.storage.materialize.get_storage_backend', return_value=mock_storage):
                # Store with overwrite
                store_from_path("documents/test.txt", tmp_path, overwrite=True)
                
                # Verify new content
                self.assertEqual(
                    mock_storage.files["documents/test.txt"],
                    b"New content"
                )
                
                # Verify no temp keys left behind
                temp_keys = [k for k in mock_storage.files.keys() if ".tmp." in k]
                self.assertEqual(len(temp_keys), 0)
        finally:
            tmp_path.unlink()