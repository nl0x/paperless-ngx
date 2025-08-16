from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from documents.models import Document
from paperless.db import GnuPG


class Command(BaseCommand):
    help = (
        "This is how you migrate your stored documents from an encrypted "
        "state to an unencrypted one (or vice-versa)"
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--passphrase",
            help=(
                "If PAPERLESS_PASSPHRASE isn't set already, you need to specify it here"
            ),
        )

    def handle(self, *args, **options) -> None:
        try:
            self.stdout.write(
                self.style.WARNING(
                    "\n\n"
                    "WARNING: This script is going to work directly on your "
                    "document originals, so\n"
                    "WARNING: you probably shouldn't run "
                    "this unless you've got a recent backup\n"
                    "WARNING: handy.  It "
                    "*should* work without a hitch, but be safe and backup your\n"
                    "WARNING: stuff first.\n\n"
                    "Hit Ctrl+C to exit now, or Enter to "
                    "continue.\n\n",
                ),
            )
            _ = input()
        except KeyboardInterrupt:
            return

        passphrase = options["passphrase"] or settings.PASSPHRASE
        if not passphrase:
            raise CommandError(
                "Passphrase not defined.  Please set it with --passphrase or "
                "by declaring it in your environment or your config.",
            )

        self.__gpg_to_unencrypted(passphrase)

    def __gpg_to_unencrypted(self, passphrase: str) -> None:
        encrypted_files = Document.objects.filter(
            storage_type=Document.STORAGE_TYPE_GPG,
        )

        for document in encrypted_files:
            self.stdout.write(f"Decrypting {document}")

            # Read encrypted files and decrypt them
            with document.source_file.open() as file_handle:
                raw_document = GnuPG.decrypted(file_handle, passphrase)
            with document.thumbnail_file.open() as file_handle:
                raw_thumb = GnuPG.decrypted(file_handle, passphrase)

            # Verify filename ends with .gpg
            ext: str = Path(document.filename).suffix
            if not ext == ".gpg":
                raise CommandError(
                    f"Abort: encrypted file {document.filename} does not "
                    f"end with .gpg",
                )

            # Store old keys for deletion
            old_source_key = document.storage_key_source()
            old_thumb_key = document.storage_key_thumbnail()

            # Update document to unencrypted
            document.storage_type = Document.STORAGE_TYPE_UNENCRYPTED
            document.filename = Path(document.filename).stem

            # Write decrypted content to new location
            document.source_file.write(raw_document)
            document.thumbnail_file.write(raw_thumb)

            # Update database
            Document.objects.filter(id=document.id).update(
                storage_type=document.storage_type,
                filename=document.filename,
            )

            # Delete old encrypted files
            from documents.storage.file_abstraction import DocumentFile
            if old_source_key:
                DocumentFile(old_source_key).delete()
            if old_thumb_key:
                DocumentFile(old_thumb_key).delete()
