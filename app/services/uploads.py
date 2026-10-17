"""Manual image uploads from the portal (not part of the AI content engine)."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from PIL import Image

from app.config import get_settings

CLOUDINARY_FOLDER = "storias/manual"


class UploadError(Exception):
    pass


@dataclass(frozen=True)
class UploadedImage:
    url: str
    public_id: str


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def validate_image(data: bytes) -> None:
    try:
        Image.open(io.BytesIO(data)).load()
    except Exception as exc:
        raise UploadError("El archivo no es una imagen válida.") from exc


def _configure_cloudinary() -> None:
    settings = get_settings()
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        raise UploadError("Cloudinary no está configurado en el entorno.")
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
    )


def upload_image(data: bytes, client_id: str, tag: str) -> UploadedImage:
    """Upload one uniquely-addressed manual image for safe compensation."""
    validate_image(data)
    _configure_cloudinary()
    public_id = f"{CLOUDINARY_FOLDER}/{_sanitize(client_id)}/{_sanitize(tag)}-{uuid4().hex}"
    try:
        result = cloudinary.uploader.upload(data, public_id=public_id, resource_type="image")
    except Exception as exc:
        raise UploadError(f"Error subiendo la imagen a Cloudinary: {exc}") from exc
    return UploadedImage(url=result["secure_url"], public_id=public_id)


def delete_image(public_id: str) -> None:
    """Destroy exactly one manual upload during database compensation."""
    _configure_cloudinary()
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
    except Exception as exc:
        raise UploadError(f"Error eliminando la imagen de Cloudinary: {exc}") from exc
