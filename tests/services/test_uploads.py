import io
from types import SimpleNamespace

from PIL import Image

from app.services import uploads


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _settings():
    return SimpleNamespace(
        cloudinary_cloud_name="cloud",
        cloudinary_api_key="key",
        cloudinary_api_secret="secret",
    )


def test_concurrent_manual_uploads_get_distinct_public_ids(monkeypatch):
    public_ids = []
    monkeypatch.setattr(uploads, "get_settings", _settings)
    monkeypatch.setattr(uploads.cloudinary, "config", lambda **kwargs: None)

    def fake_upload(data, *, public_id, resource_type):
        public_ids.append(public_id)
        return {"secure_url": f"https://cdn/{public_id}"}

    monkeypatch.setattr(uploads.cloudinary.uploader, "upload", fake_upload)

    first = uploads.upload_image(_png(), "client-1", "2026-09-25-1000")
    second = uploads.upload_image(_png(), "client-1", "2026-09-25-1000")

    assert first.public_id != second.public_id
    assert public_ids == [first.public_id, second.public_id]
    assert first.url.endswith(first.public_id)
    assert second.url.endswith(second.public_id)


def test_delete_image_destroys_exact_public_id(monkeypatch):
    destroyed = []
    monkeypatch.setattr(uploads, "get_settings", _settings)
    monkeypatch.setattr(uploads.cloudinary, "config", lambda **kwargs: None)
    monkeypatch.setattr(
        uploads.cloudinary.uploader,
        "destroy",
        lambda public_id, **kwargs: destroyed.append((public_id, kwargs)),
    )

    uploads.delete_image("storias/manual/client/exact-resource")

    assert destroyed == [(
        "storias/manual/client/exact-resource",
        {"resource_type": "image", "invalidate": True},
    )]
