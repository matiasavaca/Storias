"""Manual image uploads from the portal (not part of the AI content engine)."""
from __future__ import annotations

import io
import re

import cloudinary
import cloudinary.uploader
from PIL import Image

from app.config import get_settings

CLOUDINARY_FOLDER = "storias/manual"


class UploadError(Exception):
    pass


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def validate_image(data: bytes) -> None:
    try:
        Image.open(io.BytesIO(data)).load()
    except Exception as exc:
        raise UploadError("El archivo no es una imagen válida.") from exc


def upload_image(data: bytes, client_id: str, tag: str) -> str:
    """Uploads a manually-provided image and returns its Cloudinary URL."""
    validate_image(data)
    settings = get_settings()
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        raise UploadError("Cloudinary no está configurado en el entorno.")
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
    )
    public_id = f"{CLOUDINARY_FOLDER}/{_sanitize(client_id)}/{_sanitize(tag)}"
    try:
        result = cloudinary.uploader.upload(data, public_id=public_id, resource_type="image")
    except Exception as exc:
        raise UploadError(f"Error subiendo la imagen a Cloudinary: {exc}") from exc
    return result["secure_url"]
