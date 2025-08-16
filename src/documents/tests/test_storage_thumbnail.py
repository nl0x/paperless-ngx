"""
Tests for thumbnail storage via storage abstraction.
"""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from documents.models import Document
from documents.storage import get_storage_backend
from documents.tests.utils import DirectoriesMixin


class ThumbnailStorageTest(DirectoriesMixin, TestCase):
    """Test that thumbnails are stored via storage abstraction."""
    
    def setUp(self):
        super().setUp()
        # Reset storage backend to pick up test settings
        from documents.storage import reset_storage_backend
        reset_storage_backend()
    
    def test_write_thumbnail_method(self):
        """Test that thumbnail file write stores via storage backend."""
        # Create a document
        doc = Document.objects.create(
            title="Test Doc",
            content="Test content",
            checksum="test123",
            mime_type="application/pdf",
            filename="test.pdf",
        )
        
        # Create a dummy thumbnail file
        thumbnail_content = b"fake thumbnail content"
        temp_thumb = Path(self.dirs.scratch_dir) / "thumb.webp"
        temp_thumb.write_bytes(thumbnail_content)
        
        # Write thumbnail using the new API
        with open(temp_thumb, 'rb') as f:
            doc.thumbnail_file.write(f)
        
        # Get storage backend and verify
        storage = get_storage_backend()
        thumbnail_key = doc.storage_key_thumbnail()
        
        # Verify thumbnail exists in storage
        self.assertTrue(storage.exists(thumbnail_key))
        
        # Verify content matches
        retrieved = storage.retrieve(thumbnail_key)
        content = retrieved.read()
        retrieved.close()
        self.assertEqual(content, thumbnail_content)
    
    def test_thumbnail_retrieved_via_storage(self):
        """Test that thumbnail_file property uses storage backend."""
        # Create a document
        doc = Document.objects.create(
            title="Test Doc", 
            content="Test content",
            checksum="test456",
            mime_type="application/pdf",
            filename="test2.pdf",
        )
        
        # Store a thumbnail via storage
        storage = get_storage_backend()
        thumbnail_content = b"test thumbnail data"
        import io
        storage.store(doc.storage_key_thumbnail(), io.BytesIO(thumbnail_content))
        
        # Retrieve via document property using new API
        retrieved_content = doc.thumbnail_file.read()
        
        self.assertEqual(retrieved_content, thumbnail_content)
    
    def test_thumbnail_key_format(self):
        """Test that thumbnail storage keys have correct format."""
        # Test regular document
        doc = Document.objects.create(
            pk=123,
            title="Test",
            content="content",
            checksum="abc",
            storage_type=Document.STORAGE_TYPE_UNENCRYPTED,
        )
        self.assertEqual(doc.storage_key_thumbnail(), "documents/thumbnails/0000123.webp")
        
        # Test GPG encrypted document
        doc_gpg = Document.objects.create(
            pk=456,
            title="Test GPG",
            content="content",
            checksum="def",
            storage_type=Document.STORAGE_TYPE_GPG,
        )
        self.assertEqual(doc_gpg.storage_key_thumbnail(), "documents/thumbnails/0000456.webp.gpg")