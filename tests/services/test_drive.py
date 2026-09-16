import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.services import drive


def _png(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color).save(buf, format="PNG")
    return buf.getvalue()


_ONE, _TWO, _FIRST = _png((255, 0, 0)), _png((0, 255, 0)), _png((0, 0, 255))


def test_shared_drive_paginates_downloads_and_preserves_order(monkeypatch):
    files = Mock()
    files.list.return_value.execute.side_effect = [
        {"files": [{"id": "one", "name": "one.jpg"}], "nextPageToken": "page-2"},
        {"files": [{"id": "two", "name": "two.png"}]},
    ]
    files.get_media.return_value.execute.side_effect = [_ONE, _TWO]
    monkeypatch.setattr(drive, "_drive_client", lambda: SimpleNamespace(files=lambda: files))
    assert drive.list_images("folder") == [("one", "one.jpg", _ONE), ("two", "two.png", _TWO)]
    calls = files.list.call_args_list
    assert len(calls) == 2
    assert calls[1].kwargs["pageToken"] == "page-2"
    for call in calls:
        assert call.kwargs["supportsAllDrives"] is True
        assert call.kwargs["includeItemsFromAllDrives"] is True
        assert "mimeType contains 'image/'" in call.kwargs["q"]
        assert "trashed = false" in call.kwargs["q"]
    assert files.get_media.call_args.kwargs == {"fileId": "two", "supportsAllDrives": True}


def test_empty_folder_returns_no_images(monkeypatch):
    files = Mock()
    files.list.return_value.execute.return_value = {"files": []}
    monkeypatch.setattr(drive, "_drive_client", lambda: SimpleNamespace(files=lambda: files))
    assert drive.list_images("empty") == []
    files.get_media.assert_not_called()


def test_missing_folder_fails_before_google(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(drive, "_drive_client", factory)
    with pytest.raises(ValueError, match="drive_folder_id"):
        drive.list_images("")
    factory.assert_not_called()


def test_first_image_downloads_only_first_sorted_file(monkeypatch):
    files = Mock()
    files.list.return_value.execute.return_value = {"files": [
        {"id": "z", "name": "z.jpg"}, {"id": "a", "name": "a.jpg"},
    ]}
    files.get_media.return_value.execute.return_value = _FIRST
    monkeypatch.setattr(drive, "_drive_client", lambda: SimpleNamespace(files=lambda: files))

    assert drive.first_image("folder") == ("a", "a.jpg", _FIRST)
    files.get_media.assert_called_once_with(fileId="a", supportsAllDrives=True)


def test_unreadable_image_is_skipped_not_fatal(monkeypatch):
    files = Mock()
    files.list.return_value.execute.return_value = {"files": [
        {"id": "bad", "name": "corrupt.heic"}, {"id": "good", "name": "good.png"},
    ]}
    files.get_media.return_value.execute.side_effect = [b"not-a-real-image", _FIRST]
    monkeypatch.setattr(drive, "_drive_client", lambda: SimpleNamespace(files=lambda: files))

    assert drive.list_images("folder") == [("good", "good.png", _FIRST)]


def test_first_image_skips_unreadable_files_until_one_decodes(monkeypatch):
    files = Mock()
    files.list.return_value.execute.return_value = {"files": [
        {"id": "bad", "name": "corrupt.heic"}, {"id": "good", "name": "good.png"},
    ]}
    files.get_media.return_value.execute.side_effect = [b"not-a-real-image", _FIRST]
    monkeypatch.setattr(drive, "_drive_client", lambda: SimpleNamespace(files=lambda: files))

    assert drive.first_image("folder") == ("good", "good.png", _FIRST)
