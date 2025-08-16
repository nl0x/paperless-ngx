import hashlib
import logging
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Final

from celery import states
from django.conf import settings
from django.utils import timezone
from tqdm import tqdm

from documents.models import Document
from documents.models import PaperlessTask
from documents.storage import get_storage_backend
from paperless.config import GeneralConfig


class SanityCheckMessages:
    def __init__(self):
        self._messages: dict[int, list[dict]] = defaultdict(list)
        self.has_error = False
        self.has_warning = False

    def error(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.ERROR, "message": message})
        self.has_error = True

    def warning(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.WARNING, "message": message})
        self.has_warning = True

    def info(self, doc_pk, message):
        self._messages[doc_pk].append({"level": logging.INFO, "message": message})

    def log_messages(self):
        logger = logging.getLogger("paperless.sanity_checker")

        if len(self._messages) == 0:
            logger.info("Sanity checker detected no issues.")
        else:
            # Query once
            all_docs = Document.global_objects.all()

            for doc_pk in self._messages:
                if doc_pk is not None:
                    doc = all_docs.get(pk=doc_pk)
                    logger.info(
                        f"Detected following issue(s) with document #{doc.pk},"
                        f" titled {doc.title}",
                    )
                for msg in self._messages[doc_pk]:
                    logger.log(msg["level"], msg["message"])

    def __len__(self):
        return len(self._messages)

    def __getitem__(self, item):
        return self._messages[item]


class SanityCheckFailedException(Exception):
    pass


def check_sanity(*, progress=False, scheduled=True) -> SanityCheckMessages:
    paperless_task = PaperlessTask.objects.create(
        task_id=uuid.uuid4(),
        type=PaperlessTask.TaskType.SCHEDULED_TASK
        if scheduled
        else PaperlessTask.TaskType.MANUAL_TASK,
        task_name=PaperlessTask.TaskName.CHECK_SANITY,
        status=states.STARTED,
        date_created=timezone.now(),
        date_started=timezone.now(),
    )
    messages = SanityCheckMessages()

    # Get storage backend
    storage = get_storage_backend()
    
    # Get all files/objects from storage
    present_files = set(storage.list_keys())
    
    # Remove known non-document files
    # Note: media.lock is a local file for process coordination, not stored in S3
    # For local storage, we might see it in the file list
    general_config = GeneralConfig()
    app_logo = general_config.app_logo or settings.APP_LOGO
    if app_logo:
        # Convert app logo path to storage key format
        logo_key = app_logo.lstrip("/")
        if logo_key in present_files:
            present_files.remove(logo_key)

    for doc in tqdm(Document.global_objects.all(), disable=not progress):
        # Check sanity of the thumbnail
        thumbnail = doc.thumbnail_file
        if thumbnail and thumbnail.key:
            if not thumbnail.exists:
                messages.error(doc.pk, "Thumbnail of document does not exist.")
            else:
                if thumbnail.key in present_files:
                    present_files.remove(thumbnail.key)
                try:
                    _ = thumbnail.read()
                except (OSError, FileNotFoundError) as e:
                    messages.error(doc.pk, f"Cannot read thumbnail file of document: {e}")
        else:
            messages.error(doc.pk, "Document has no thumbnail storage key.")

        # Check sanity of the original file
        # TODO: extract method
        source = doc.source_file
        if source and source.key:
            if not source.exists:
                messages.error(doc.pk, "Original of document does not exist.")
            else:
                if source.key in present_files:
                    present_files.remove(source.key)
                try:
                    content = source.read()
                    checksum = hashlib.md5(content).hexdigest()
                except (OSError, FileNotFoundError) as e:
                    messages.error(doc.pk, f"Cannot read original file of document: {e}")
                else:
                    if checksum != doc.checksum:
                        messages.error(
                            doc.pk,
                            "Checksum mismatch. "
                            f"Stored: {doc.checksum}, actual: {checksum}.",
                        )
        else:
            messages.error(doc.pk, "Document has no source file storage key.")

        # Check sanity of the archive file.
        if doc.archive_checksum is not None and doc.archive_filename is None:
            messages.error(
                doc.pk,
                "Document has an archive file checksum, but no archive filename.",
            )
        elif doc.archive_checksum is None and doc.archive_filename is not None:
            messages.error(
                doc.pk,
                "Document has an archive file, but its checksum is missing.",
            )
        elif doc.has_archive_version:
            archive = doc.archive_file
            if archive and archive.key:
                if not archive.exists:
                    messages.error(doc.pk, "Archived version of document does not exist.")
                else:
                    if archive.key in present_files:
                        present_files.remove(archive.key)
                    try:
                        content = archive.read()
                        checksum = hashlib.md5(content).hexdigest()
                    except (OSError, FileNotFoundError) as e:
                        messages.error(
                            doc.pk,
                            f"Cannot read archive file of document : {e}",
                        )
                    else:
                        if checksum != doc.archive_checksum:
                            messages.error(
                                doc.pk,
                                "Checksum mismatch of archived document. "
                                f"Stored: {doc.archive_checksum}, "
                                f"actual: {checksum}.",
                            )
            else:
                messages.error(doc.pk, "Document has archive version but no storage key.")

        # other document checks
        if not doc.content:
            messages.info(doc.pk, "Document contains no OCR data")

    for extra_file in present_files:
        messages.warning(None, f"Orphaned file in media dir: {extra_file}")

    paperless_task.status = states.SUCCESS if not messages.has_error else states.FAILURE
    # result is concatenated messages
    paperless_task.result = f"{len(messages)} issues found."
    if messages.has_error:
        paperless_task.result += " Check logs for details."
    paperless_task.date_done = timezone.now()
    paperless_task.save(update_fields=["status", "result", "date_done"])
    return messages
