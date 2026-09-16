"""Composicion de imagen para Stories con Pillow.

Migrado LITERAL de ``editar_imagen``/``panel/app.py``: crop 9:16, ajuste
de contraste/color/tinte, wrap de texto por numero de historia, CTA y
logo superpuesto. Solo cambia de donde sale el logo (bytes recibidos por
parametro, ya descargados por content.py) y donde viven las fuentes
(package ``assets/``).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

logger = logging.getLogger(__name__)

# Fuentes que acompanan al motor (unicas que se bundlean en assets/). Se
# intentan en orden hasta encontrar una que exista; como ultimo recurso cae
# en ImageFont.load_default(), lo cual se loguea porque produce Stories con
# texto en un bitmap ilegible sin marca.
_FONT_PATHS = [
    str(Path(__file__).parent / "assets" / "Raleway[wght].ttf"),
    str(Path(__file__).parent / "assets" / "JosefinSans[wght].ttf"),
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/calibril.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

FONT_WEIGHT = 600  # SemiBold - legible sobre fotos sin perder elegancia

CTA_TEXT = "Agenda tu consulta"  # texto del link de CTA dibujado sobre la imagen


def _load_font(size: int, weight: int = FONT_WEIGHT) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            f = ImageFont.truetype(path, size)
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass  # fuente estatica, sin eje de peso
            return f
        except Exception:
            continue
    logger.error("No bundled or system font could be loaded; falling back to PIL's default bitmap font")
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = f"{line} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_w and line:
            lines.append(line)
            line = w
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def componer_historia(
    image_bytes: bytes,
    frase: str,
    agregar_cta: bool,
    num_historia: int = 1,
    logo_bytes: bytes | None = None,
    calendly_link: str | None = None,
) -> bytes:
    """Compone la imagen final (1080x1920) con ``frase`` superpuesta.

    ``logo_bytes`` puede ser None: en ese caso no se superpone logo (el
    cliente no tiene logo_url configurado). El CTA de texto se dibuja solo
    si ``agregar_cta`` y ``calendly_link`` estan seteados, igual que el
    comportamiento original sobre el fondo de imagen.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    target_w, target_h = 1080, 1920
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        new_h = img.height
        new_w = int(new_h * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, new_h))
    else:
        new_w = img.width
        new_h = int(new_w / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, new_w, top + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)

    img_rgb = img.convert("RGB")
    img_rgb = ImageEnhance.Contrast(img_rgb).enhance(0.82)
    img_rgb = ImageEnhance.Color(img_rgb).enhance(0.88)

    r, g, b = img_rgb.split()
    r = r.point(lambda i: min(255, int(i * 1.04)))
    b = b.point(lambda i: int(i * 0.94))
    img_rgb = Image.merge("RGB", (r, g, b))

    img_rgba = img_rgb.convert("RGBA")
    overlay = Image.new("RGBA", img_rgba.size, (0, 0, 0, 65))
    img_final = Image.alpha_composite(img_rgba, overlay)
    draw = ImageDraw.Draw(img_final)

    font_size = 75
    font_texto = _load_font(font_size)

    WHITE = (255, 255, 255, 255)
    WHITE_DIM = (255, 255, 255, 190)

    margin = 85
    max_w = target_w - margin * 2

    lines = _wrap_text(frase, font_texto, draw, max_w)
    line_h = font_size + 35
    total_text_h = len(lines) * line_h

    pos_ratios = {1: 0.42, 2: 0.50, 3: 0.54, 4: 0.46}
    base_y = int(target_h * pos_ratios.get(num_historia, 0.46)) - total_text_h // 2

    alineacion = "centro" if num_historia == 1 else "izquierda"

    for i, line in enumerate(lines):
        y = base_y + i * line_h
        if alineacion == "centro":
            bbox = draw.textbbox((0, 0), line, font=font_texto)
            x = (target_w - (bbox[2] - bbox[0])) // 2
        else:
            x = margin
        draw.text((x, y), line, font=font_texto, fill=WHITE)

    if agregar_cta and calendly_link:
        font_cta = _load_font(50)
        cta_y = base_y + total_text_h + 60
        draw.text((margin, cta_y), CTA_TEXT, font=font_cta, fill=WHITE_DIM)

    if logo_bytes:
        logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        alpha = logo.split()[3]
        logo = Image.new("RGBA", logo.size, (255, 255, 255, 180))
        logo.putalpha(alpha.point(lambda a: 180 if a > 10 else 0))
        logo_target_w = 240
        ratio = logo_target_w / logo.width
        logo_h = int(logo.height * ratio)
        logo = logo.resize((logo_target_w, logo_h), Image.LANCZOS)
        logo_x = (target_w - logo_target_w) // 2
        logo_y = target_h - 220
        img_final.paste(logo, (logo_x, logo_y), logo)

    output = io.BytesIO()
    img_final.convert("RGB").save(output, format="JPEG", quality=95)
    return output.getvalue()