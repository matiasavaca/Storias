"""Modelos Pydantic del contrato de integracion (AGENTS.md, seccion 3).

Copiados tal cual del contrato: son la superficie publica que el portal
(Codex) va a usar para llamar al motor.
"""

from pydantic import BaseModel


class ClientContentConfig(BaseModel):
    client_id: str
    nombre_negocio: str
    business_description: str
    weekly_focus: str | None = None
    tone_examples: list[list[str]]      # cada item: las 4 historias de un hilo de ejemplo
    topics: list[str] | None = None
    logo_url: str | None = None
    calendly_link: str | None = None
    prob_link: float = 0.0


class ImagenCandidata(BaseModel):
    drive_file_id: str
    drive_file_name: str
    image_bytes: bytes                  # el portal ya la bajo de Drive


class HiloGenerado(BaseModel):
    historias: list[str]                # 4 textos, en orden
    imagenes_originales_url: list[str]  # Cloudinary, SIN texto (para re-editar despues)
    imagenes_editadas_url: list[str]    # Cloudinary, CON texto
    drive_file_ids_usados: list[str]    # el portal marca estos como last_used_at = ahora en client_images
    cta_agregado: bool = False          # si el motor efectivamente dibujo el CTA (sorteo por prob_link)


class ResultadoPublicacion(BaseModel):
    ok: bool
    ig_media_id: str | None = None
    error: str | None = None