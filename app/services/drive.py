"""Read-only image downloads from client folders in Google Shared Drives."""
from __future__ import annotations

import io
import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


def _is_readable_image(data: bytes) -> bool:
    try:
        Image.open(io.BytesIO(data)).load()
        return True
    except Exception:
        return False


def _drive_client():
    path = get_settings().google_service_account_file
    if not path:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE is required for Drive access")
    credentials = service_account.Credentials.from_service_account_file(
        path, scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _image_files(drive_folder_id: str):
    if not drive_folder_id:
        raise ValueError("drive_folder_id is required")
    folder = drive_folder_id.replace("\\", "\\\\").replace("'", "\\'")
    files = _drive_client().files()
    metadata = []
    token = None
    while True:
        page = files.list(
            q=f"'{folder}' in parents and trashed = false and mimeType contains 'image/'",
            fields="nextPageToken,files(id,name)", pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        metadata.extend(page.get("files", []))
        token = page.get("nextPageToken")
        if not token:
            break
    return files, sorted(metadata, key=lambda item: (item["name"], item["id"]))


def list_images(drive_folder_id: str) -> list[tuple[str, str, bytes]]:
    """Return every readable image directly inside the folder, in stable name/ID order.

    Files that fail to decode (corrupt, unsupported format like HEIC, etc.)
    are skipped with a warning instead of aborting the whole client's batch.
    """
    files, metadata = _image_files(drive_folder_id)
    images = []
    for item in metadata:
        data = files.get_media(fileId=item["id"], supportsAllDrives=True).execute()
        if not _is_readable_image(data):
            logger.warning("Skipping unreadable Drive image %s (%s)", item["id"], item["name"])
            continue
        images.append((item["id"], item["name"], data))
    return images


def first_image(drive_folder_id: str) -> tuple[str, str, bytes] | None:
    """Return the first readable image, downloading bytes only until one decodes."""
    files, metadata = _image_files(drive_folder_id)
    for item in metadata:
        data = files.get_media(fileId=item["id"], supportsAllDrives=True).execute()
        if not _is_readable_image(data):
            logger.warning("Skipping unreadable Drive image %s (%s)", item["id"], item["name"])
            continue
        return item["id"], item["name"], data
    return None
