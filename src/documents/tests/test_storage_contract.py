"""
Contract tests for storage backends.

These tests define the expected behavior for any storage backend implementation.
They are backend-agnostic and test only the interface contract.
"""

import io
import tempfile
from pathlib import Path
from abc import ABC
from unittest import TestCase

from documents.storage.base import StorageBackend
from documents.storage.local import LocalFileStorage


class StorageContractTestCase(TestCase, ABC):
    """
    Base test case for storage backend contract tests.
    
    Subclass this and provide a storage_backend property to test
    any storage implementation.
    """
    
    def get_storage_backend(self) -> StorageBackend:
        """Override this to provide the storage backend to test."""
        # Skip this test if it's the base class itself
        if self.__class__ == StorageContractTestCase:
            self.skipTest("Abstract base class - not meant to be run directly")
        raise NotImplementedError
    
    def setUp(self):
        """Set up test fixtures."""
        self.storage = self.get_storage_backend()
        self.test_content = b"Test document content"
        self.test_key = "test/document.pdf"
    
    def tearDown(self):
        """Clean up after tests."""
        # Try to clean up test files
        try:
            self.storage.delete(self.test_key)
        except:
            pass
    
    def test_store_and_retrieve(self):
        """Test basic store and retrieve operations."""
        # Store a document
        content_stream = io.BytesIO(self.test_content)
        self.storage.store(self.test_key, content_stream)
        
        # Retrieve it back
        retrieved = self.storage.retrieve(self.test_key)
        retrieved_content = retrieved.read()
        retrieved.close()
        
        self.assertEqual(retrieved_content, self.test_content)
    
    def test_exists(self):
        """Test existence checking."""
        # Should not exist initially
        self.assertFalse(self.storage.exists(self.test_key))
        
        # Store a document
        content_stream = io.BytesIO(self.test_content)
        self.storage.store(self.test_key, content_stream)
        
        # Should exist now
        self.assertTrue(self.storage.exists(self.test_key))
        
        # Delete it
        self.storage.delete(self.test_key)
        
        # Should not exist anymore
        self.assertFalse(self.storage.exists(self.test_key))
    
    def test_delete_idempotent(self):
        """Test that delete is idempotent (no error if key doesn't exist)."""
        # Delete non-existent key should not raise
        self.storage.delete("non/existent/key.pdf")
        
        # Store and delete
        content_stream = io.BytesIO(self.test_content)
        self.storage.store(self.test_key, content_stream)
        self.storage.delete(self.test_key)
        
        # Delete again - should not raise
        self.storage.delete(self.test_key)
    
    def test_rename(self):
        """Test rename operation."""
        new_key = "test/renamed.pdf"
        
        # Store a document
        content_stream = io.BytesIO(self.test_content)
        self.storage.store(self.test_key, content_stream)
        
        # Rename it
        self.storage.rename(self.test_key, new_key)
        
        # Old key should not exist
        self.assertFalse(self.storage.exists(self.test_key))
        
        # New key should exist with same content
        self.assertTrue(self.storage.exists(new_key))
        retrieved = self.storage.retrieve(new_key)
        self.assertEqual(retrieved.read(), self.test_content)
        retrieved.close()
        
        # Clean up
        self.storage.delete(new_key)
    
    def test_rename_overwrites(self):
        """Test that rename overwrites destination if it exists."""
        new_key = "test/destination.pdf"
        other_content = b"Other content"
        
        # Store two documents
        self.storage.store(self.test_key, io.BytesIO(self.test_content))
        self.storage.store(new_key, io.BytesIO(other_content))
        
        # Rename should overwrite
        self.storage.rename(self.test_key, new_key)
        
        # Check that destination has the renamed content
        retrieved = self.storage.retrieve(new_key)
        self.assertEqual(retrieved.read(), self.test_content)
        retrieved.close()
        
        # Clean up
        self.storage.delete(new_key)
    
    def test_rename_nonexistent_raises(self):
        """Test that renaming non-existent key raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.storage.rename("non/existent.pdf", "new/name.pdf")
    
    def test_retrieve_nonexistent_raises(self):
        """Test that retrieving non-existent key raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.storage.retrieve("non/existent.pdf")
    
    def test_list_keys_empty(self):
        """Test listing keys when empty."""
        # Clean up any existing test files
        for key in self.storage.list_keys("test/"):
            self.storage.delete(key)
        
        # Should return empty list
        keys = self.storage.list_keys("test/")
        self.assertEqual(keys, [])
    
    def test_list_keys_with_files(self):
        """Test listing keys with multiple files."""
        keys_to_create = [
            "test/doc1.pdf",
            "test/doc2.pdf",
            "test/subdir/doc3.pdf",
            "other/doc4.pdf",
        ]
        
        # Store multiple documents
        for key in keys_to_create:
            self.storage.store(key, io.BytesIO(b"content"))
        
        # List all test/ keys
        test_keys = self.storage.list_keys("test/")
        self.assertIn("test/doc1.pdf", test_keys)
        self.assertIn("test/doc2.pdf", test_keys)
        self.assertIn("test/subdir/doc3.pdf", test_keys)
        self.assertNotIn("other/doc4.pdf", test_keys)
        
        # List with more specific prefix
        subdir_keys = self.storage.list_keys("test/subdir/")
        self.assertEqual(len(subdir_keys), 1)
        self.assertIn("test/subdir/doc3.pdf", subdir_keys)
        
        # Clean up
        for key in keys_to_create:
            self.storage.delete(key)
    
    def test_list_keys_sorted(self):
        """Test that list_keys returns sorted results."""
        keys_to_create = [
            "test/zebra.pdf",
            "test/apple.pdf",
            "test/banana.pdf",
        ]
        
        # Store in non-alphabetical order
        for key in keys_to_create:
            self.storage.store(key, io.BytesIO(b"content"))
        
        # Should return sorted
        listed = self.storage.list_keys("test/")
        expected = ["test/apple.pdf", "test/banana.pdf", "test/zebra.pdf"]
        self.assertEqual([k for k in listed if k.startswith("test/") and k.endswith(".pdf")], expected)
        
        # Clean up
        for key in keys_to_create:
            self.storage.delete(key)
    
    def test_forward_slash_keys(self):
        """Test that keys use forward slashes regardless of OS."""
        # Store with forward slashes
        key = "test/subdir/document.pdf"
        self.storage.store(key, io.BytesIO(b"content"))
        
        # List should return with forward slashes
        keys = self.storage.list_keys("test/")
        matching = [k for k in keys if "document.pdf" in k]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0], key)
        
        # Clean up
        self.storage.delete(key)
    
    def test_store_overwrites(self):
        """Test that storing to existing key overwrites content."""
        new_content = b"New content"
        
        # Store initial content
        self.storage.store(self.test_key, io.BytesIO(self.test_content))
        
        # Store new content to same key
        self.storage.store(self.test_key, io.BytesIO(new_content))
        
        # Should have new content
        retrieved = self.storage.retrieve(self.test_key)
        self.assertEqual(retrieved.read(), new_content)
        retrieved.close()
    
    def test_binary_content(self):
        """Test storing and retrieving binary content."""
        # Create some binary content (not valid UTF-8)
        binary_content = bytes(range(256))
        
        # Store and retrieve
        self.storage.store(self.test_key, io.BytesIO(binary_content))
        retrieved = self.storage.retrieve(self.test_key)
        self.assertEqual(retrieved.read(), binary_content)
        retrieved.close()
    
    def test_empty_file(self):
        """Test storing and retrieving empty file."""
        # Store empty content
        self.storage.store(self.test_key, io.BytesIO(b""))
        
        # Should exist
        self.assertTrue(self.storage.exists(self.test_key))
        
        # Should retrieve empty content
        retrieved = self.storage.retrieve(self.test_key)
        self.assertEqual(retrieved.read(), b"")
        retrieved.close()
    
    def test_unicode_keys(self):
        """Test storing and retrieving files with Unicode characters in keys."""
        # Test various Unicode characters
        unicode_keys = [
            "test/äöü document.pdf",  # German umlauts
            "test/文档.pdf",  # Chinese characters
            "test/документ.pdf",  # Cyrillic
            "test/file with spaces.pdf",  # Spaces
            "test/ä space ✓.pdf",  # Mixed special chars
        ]
        
        for key in unicode_keys:
            # Store
            self.storage.store(key, io.BytesIO(b"unicode test"))
            
            # Should exist
            self.assertTrue(self.storage.exists(key), f"Key should exist: {key}")
            
            # Should retrieve
            retrieved = self.storage.retrieve(key)
            content = retrieved.read()
            retrieved.close()
            self.assertEqual(content, b"unicode test", f"Content mismatch for: {key}")
            
            # Should appear in listings
            prefix = "test/"
            keys = self.storage.list_keys(prefix)
            # Check if our key is in the list (handle potential normalization)
            found = any(key in k or k.endswith(key.split('/')[-1]) for k in keys)
            self.assertTrue(found, f"Key not found in listing: {key}")
            
            # Clean up
            self.storage.delete(key)


class LocalFileStorageContractTest(StorageContractTestCase):
    """Test LocalFileStorage implementation against the contract."""
    
    def setUp(self):
        """Create temporary directory for testing."""
        self.temp_dir = tempfile.mkdtemp()
        super().setUp()
    
    def tearDown(self):
        """Clean up temporary directory."""
        super().tearDown()
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def get_storage_backend(self) -> StorageBackend:
        """Provide LocalFileStorage for testing."""
        return LocalFileStorage(Path(self.temp_dir))
    
    def test_directory_traversal_protection(self):
        """Test that directory traversal attacks are prevented."""
        # Try various directory traversal patterns
        bad_keys = [
            "../escaped.pdf",
            "../../escaped.pdf",
            "test/../../../escaped.pdf",
            "/absolute/path.pdf",
        ]
        
        for bad_key in bad_keys:
            with self.assertRaises(ValueError, msg=f"Should reject key: {bad_key}"):
                self.storage.store(bad_key, io.BytesIO(b"content"))
    
    def test_dots_in_filename(self):
        """Test that filenames with dots (but not ..) are allowed."""
        # These should be allowed
        valid_keys = [
            "test/my..scan.pdf",
            "test/file...pdf",
            "test/v1.2.3.pdf",
            "test/.hidden.pdf",  # Hidden files
        ]
        
        for key in valid_keys:
            # Should not raise
            self.storage.store(key, io.BytesIO(b"content"))
            self.assertTrue(self.storage.exists(key), f"Key should exist: {key}")
            # Clean up
            self.storage.delete(key)
    
    def test_directory_cleanup(self):
        """Test that empty directories are cleaned up (local-specific behavior)."""
        key = "deep/nested/directory/structure/file.pdf"
        
        # Store file
        self.storage.store(key, io.BytesIO(b"content"))
        
        # Directory should exist
        dir_path = Path(self.temp_dir) / "deep" / "nested" / "directory" / "structure"
        self.assertTrue(dir_path.exists())
        
        # Delete file
        self.storage.delete(key)
        
        # Empty directories should be cleaned up
        self.assertFalse(dir_path.exists())
        self.assertFalse((Path(self.temp_dir) / "deep").exists())