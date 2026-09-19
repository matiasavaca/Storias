"""Tests for the font selection in app/engine/imaging.py.

FONT_CHOICES is what the portal exposes for the per-client typography
picker; every key must resolve to a real, loadable bundled .ttf so a typo
here can never surface as a broken Story image in production.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

from app.engine import imaging


def test_every_font_choice_has_a_matching_bundled_file():
    assert set(imaging.FONT_CHOICES) == set(imaging._FONT_FILES)


def test_every_bundled_font_file_exists_and_loads():
    assets_dir = Path(imaging.__file__).parent / "assets"
    for key, filename in imaging._FONT_FILES.items():
        path = assets_dir / filename
        assert path.exists(), f"missing font file for '{key}': {filename}"
        ImageFont.truetype(str(path), 40)  # raises if not a valid font file


def test_load_font_uses_the_requested_choice():
    font = imaging._load_font(40, font_choice="poppins")
    family, _ = font.getname()
    assert "poppins" in family.lower()


def test_load_font_defaults_to_historical_fallback_when_no_choice():
    font = imaging._load_font(40, font_choice=None)
    family, _ = font.getname()
    assert "raleway" in family.lower()


def test_load_font_falls_back_when_choice_is_unrecognized():
    # Never crash a Story render just because font_choice holds a stale or
    # unrecognized key — fall back to the same default as font_choice=None.
    font = imaging._load_font(40, font_choice="not-a-real-font-key")
    family, _ = font.getname()
    assert "raleway" in family.lower()
