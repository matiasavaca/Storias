"""Motor de contenido multi-cliente (Storias).

Migracion de ``main.py`` + ``panel/app.py`` a funciones puras y sin estado.
Nada de lo especifico de CUAN queda hardcodeado: personaje, tono, temas,
logo, Calendly y prob. de CTA vienen de ``ClientContentConfig``.

Dependencias de entorno (las credenciales no viajan por parametro porque
el contrato no las incluye):
  - ``ANTHROPIC_API_KEY``
  - ``CLOUDINARY_CLOUD_NAME`` / ``CLOUDINARY_API_KEY`` / ``CLOUDINARY_API_SECRET``

Decisiones de migracion documentadas:
  - El modelo de Claude es ``CLAUDE_MODEL``. El ``"claude-sonnet-4-6"`` del
    original no es un modelo valido; se corrigio a ``claude-sonnet-5`` como
    constante unica.
  - El logo del cliente viene como URL en ``config.logo_url`` (el contrato no
    pasa bytes por parametro). El engine la descarga con ``requests`` y la
    cachea por URL en memoria; si falla la descarga o no hay URL, la historia
    se compone sin logo (nunca tira el hilo por el logo).
  - ``generar_hilo`` muestra a Claude la PRIMERA imagen (igual que el original,
    que pasaba solo la imagen principal) y compone cada texto sobre su imagen:
    imagen i -> historia i.
  - Si Claude devuelve menos de 4 historias no se rellena con texto inventado
    (el original hardcodeaba "Escribi COCINA..."): se levanta
    ``ClaudeGenerationError``. El engine no inventa contenido de cliente.
"""

from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import time

import anthropic
import cloudinary
import cloudinary.uploader
import requests
from PIL import Image

from .exceptions import (
    ClaudeGenerationError,
    EngineError,
    ImageProcessingError,
    MetaPublishError,
)
from .imaging import componer_historia
from .schemas import (
    ClientContentConfig,
    HiloGenerado,
    ImagenCandidata,
    ResultadoPublicacion,
)

# Modelo de Claude para generar las historias. El "claude-sonnet-4-6" del
# main.py original no es un modelo valido; se corrige aca como constante
# unica y facil de cambiar.
CLAUDE_MODEL = "claude-sonnet-5"

# Tokens maximos para la respuesta de Claude (mismo valor que el original).
CLAUDE_MAX_TOKENS = 400

# Tema generico de fallback: solo si el cliente no define topics ni
# weekly_focus. A proposito no menciona nada de cocinas.
TEMA_FALLBACK = (
    "un consejo practico y veraz sobre el trabajo de este negocio, "
    "que sirva de ayuda real a su publico"
)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

# Prefijo de los public_id de Cloudinary. Por cliente se agrega
# "/{client_id}/{timestamp}".
CLOUDINARY_FOLDER = "storias"

# Cache en memoria del logo descargado, keyed por URL.
_LOGO_CACHE: dict[str, bytes | None] = {}


# -----------------------------------------
# PROMPT
# -----------------------------------------
def _armar_prompt(config: ClientContentConfig) -> str:
    """Arma el prompt completo de Claude a partir de la config del cliente.

    Expuesta para poder testearla por separado (ver
    ``tests/engine/test_content.py``).
    """
    tema = _elegir_tema(config)

    if config.weekly_focus:
        consigna_tema = (
            f"Generá UN hilo de exactamente 4 historias de Instagram "
            f"sobre este tema (obligatorio esta semana): {tema}"
        )
    else:
        consigna_tema = (
            f"Generá UN hilo de exactamente 4 historias de Instagram "
            f"sobre este tema: {tema}"
        )

    return (
        f"{config.business_description}\n\n"
        f"{consigna_tema}\n\n"
        f"{_formatear_ejemplos(config.nombre_negocio, config.tone_examples)}\n\n"
        "REGLAS DE TONO (muy importante):\n"
        "- Lenguaje simple, cotidiano, como le hablarías a un amigo\n"
        "- PROHIBIDO usar vocabulario técnico o de moda del rubro, "
        "salvo que sea una palabra que cualquier persona común "
        "entendería sin pensar\n"
        "- Cada historia es UNA sola idea, corta, con gancho\n"
        "- Historia 1: una afirmación o pregunta que genera intriga, "
        "conectada al tema (máx 10 palabras)\n"
        "- Historia 2: desarrolla la tensión o el problema (máx 8 palabras)\n"
        f"- Historia 3: el diferencial de {config.nombre_negocio}, "
        "la solución (máx 8 palabras)\n"
        "- Historia 4: CTA con una palabra clave en mayúsculas para "
        "escribir y agendar (máx 10 palabras)\n\n"
        "La imagen adjunta es solo inspiración visual de fondo, NO "
        "es necesario describir literalmente lo que se ve en ella. "
        "El tema asignado y el tono de los ejemplos tienen prioridad "
        "total sobre cualquier detalle de la imagen.\n\n"
        "Sin hashtags. Sin emojis, excepto opcionalmente 1 en la "
        "historia 4 si suma.\n\n"
        "Devolvé SOLO las 4 historias separadas por |||, sin "
        "numeración ni etiquetas."
    )


def _elegir_tema(config: ClientContentConfig) -> str:
    """Prioridad: weekly_focus > random de topics > fallback generico."""
    if config.weekly_focus:
        return config.weekly_focus
    if config.topics:
        return random.choice(config.topics)
    return TEMA_FALLBACK


def _formatear_ejemplos(nombre_negocio: str, tone_examples: list[list[str]]) -> str:
    bloques = []
    for i, ejemplo in enumerate(tone_examples, 1):
        bloques.append(f"Ejemplo {i}:\n{' ||| '.join(ejemplo)}")
    intro = (
        f"Estos son ejemplos REALES de hilos que ya publicó {nombre_negocio} "
        "y que funcionaron muy bien. Imitá el tono, la simpleza y la "
        "estructura exacta de estos ejemplos (no los copies, son solo "
        "referencia de estilo):"
    )
    return intro + "\n\n" + "\n\n".join(bloques)


# -----------------------------------------
# CLAUDE
# -----------------------------------------
def _limpiar_emojis(texto: str) -> str:
    """Elimina emojis y simbolos fuera del rango Latino, conservando espanol."""
    return re.sub(r"[^\x20-\x7E\u00A0-\u024F]", "", texto).strip()


def _preparar_imagen_para_claude(image_bytes: bytes) -> tuple[bytes, str]:
    """Convierte cualquier imagen soportada a JPEG para Claude Vision."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=92)
    except Exception as e:
        raise ImageProcessingError(f"Error convirtiendo imagen para Claude: {e}") from e
    return buffer.getvalue(), "image/jpeg"


def _procesar_respuesta_claude(response) -> list[str]:
    """Limpia y parsea la respuesta de Claude en 4 historias.

    Si Claude devuelve menos de 4 historias validas se levanta
    ``ClaudeGenerationError``: el engine no rellena con texto inventado.
    """
    raw = response.content[0].text.strip()
    historias = [_limpiar_emojis(h.strip()) for h in raw.split("|||")]
    historias = [h for h in historias if h][:4]
    if len(historias) < 4:
        raise ClaudeGenerationError(
            f"Claude devolvió {len(historias)} historias validas, se esperaban 4."
        )
    return historias


def _llamar_claude(config: ClientContentConfig, image_bytes: bytes) -> list[str]:
    """Llamada unica a Claude: genera las 4 historias de texto.

    Compartida por ``generar_hilo`` y ``generar_texto_de_prueba``; esta
    funcion no sube nada a Cloudinary ni toca imagenes de salida.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ClaudeGenerationError("ANTHROPIC_API_KEY no está configurada en el entorno.")

    image_bytes, media_type = _preparar_imagen_para_claude(image_bytes)
    imagen_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = _armar_prompt(config)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": imagen_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except Exception as e:
        raise ClaudeGenerationError(f"Error llamando a Claude: {e}") from e

    try:
        return _procesar_respuesta_claude(response)
    except ClaudeGenerationError:
        raise
    except Exception as e:
        raise ClaudeGenerationError(f"Error parseando respuesta de Claude: {e}") from e


# -----------------------------------------
# LOGO
# -----------------------------------------
def _descargar_logo(config: ClientContentConfig) -> bytes | None:
    """Descarga el logo del cliente desde ``config.logo_url`` (cacheado).

    Decisión (documentada en el docstring del modulo): como el contrato no
    pasa el logo por parametro, el engine lo baja de la URL. Si no hay URL
    o la descarga falla devuelve None y se compone sin logo.
    """
    if not config.logo_url:
        return None
    if config.logo_url in _LOGO_CACHE:
        return _LOGO_CACHE[config.logo_url]
    try:
        r = requests.get(config.logo_url, timeout=30)
        r.raise_for_status()
        logo_bytes = r.content
        _LOGO_CACHE[config.logo_url] = logo_bytes
        return logo_bytes
    except Exception as e:
        print(f"[engine] No se pudo descargar el logo ({config.logo_url}): {e}")
        _LOGO_CACHE[config.logo_url] = None
        return None


# -----------------------------------------
# CLOUDINARY
# -----------------------------------------
def _sanitizar_id(cliente_id: str) -> str:
    """El client_id va en el public_id de Cloudinary: solo caracteres seguros."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", cliente_id)


def _subir_cloudinary(image_bytes: bytes, public_id: str) -> str:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        raise EngineError("Credenciales de Cloudinary no configuradas en el entorno.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )
    try:
        result = cloudinary.uploader.upload(
            image_bytes,
            public_id=public_id,
            resource_type="image",
        )
    except Exception as e:
        raise EngineError(f"Error subiendo a Cloudinary: {e}") from e
    return result["secure_url"]


# -----------------------------------------
# FUNCIONES PUBLICAS DEL CONTRATO
# -----------------------------------------
def generar_hilo(config: ClientContentConfig, imagenes: list[ImagenCandidata]) -> HiloGenerado:
    """
    Genera un hilo de 4 historias a partir de exactamente 4 imagenes.

    Las imagenes ya vienen FILTRADAS por no-repeticion (lo decide el portal
    contra ``client_images.last_used_at``, no este motor). No escribe en
    ningun lado: devuelve los datos y el portal los persiste.
    """
    if len(imagenes) != 4:
        raise EngineError(
            f"generar_hilo espera exactamente 4 ImagenCandidata, recibió {len(imagenes)}. "
            "El filtrado por no-repetición lo hace el portal antes de llamar acá."
        )

    # Mismo comportamiento que el main.py original: Claude ve solo la imagen
    # principal (imagen 1) como inspiracion. Cada texto se compone despues
    # sobre su propia imagen: imagen i -> historia i.
    historias = _llamar_claude(config, imagenes[0].image_bytes)

    logo_bytes = _descargar_logo(config)
    base = f"{CLOUDINARY_FOLDER}/{_sanitizar_id(config.client_id)}/{int(time.time())}"

    urls_originales = []
    urls_editadas = []
    cta_agregado = False
    for i, (texto, imagen) in enumerate(zip(historias, imagenes), 1):
        # CTA solo en la historia 4, con probabilidad prob_link (no un gate binario).
        agregar_cta = (i == 4) and random.random() < config.prob_link
        cta_agregado = cta_agregado or agregar_cta

        # Se sube la imagen SIN texto por separado de la editada, para poder
        # re-editar despues sin perder calidad (truco de la migracion).
        url_original = _subir_cloudinary(imagen.image_bytes, f"{base}_{i}_raw")
        urls_originales.append(url_original)

        try:
            editada = componer_historia(
                imagen.image_bytes,
                texto,
                agregar_cta,
                num_historia=i,
                logo_bytes=logo_bytes,
                calendly_link=config.calendly_link,
            )
        except Exception as e:
            raise ImageProcessingError(f"Error componiendo la historia {i}: {e}") from e

        url_editada = _subir_cloudinary(editada, f"{base}_{i}")
        urls_editadas.append(url_editada)

    return HiloGenerado(
        historias=historias,
        imagenes_originales_url=urls_originales,
        imagenes_editadas_url=urls_editadas,
        drive_file_ids_usados=[imagen.drive_file_id for imagen in imagenes],
        cta_agregado=cta_agregado,
    )


def editar_historia(
    config: ClientContentConfig,
    imagen_original_bytes: bytes,
    texto_nuevo: str,
    num_historia: int,
) -> str:
    """
    Re-edita UNA historia a partir de su imagen SIN texto (nunca de la ya
    editada). Devuelve la URL nueva de Cloudinary.
    """
    logo_bytes = _descargar_logo(config)
    agregar_cta = (num_historia == 4) and random.random() < config.prob_link

    try:
        editada = componer_historia(
            imagen_original_bytes,
            texto_nuevo,
            agregar_cta,
            num_historia=num_historia,
            logo_bytes=logo_bytes,
            calendly_link=config.calendly_link,
        )
    except Exception as e:
        raise ImageProcessingError(
            f"Error re-componiendo la historia {num_historia}: {e}"
        ) from e

    base = f"{CLOUDINARY_FOLDER}/{_sanitizar_id(config.client_id)}"
    public_id = f"{base}/re_edit_{num_historia}_{int(time.time())}"
    return _subir_cloudinary(editada, public_id)


def generar_texto_de_prueba(config: ClientContentConfig, imagen: ImagenCandidata) -> list[str]:
    """
    Para el boton "Probar prompt": genera las 4 historias de texto pero NO
    sube nada a Cloudinary ni compone imagenes. Solo texto.
    """
    return _llamar_claude(config, imagen.image_bytes)


def publicar_historia(
    image_url: str,
    instagram_account_id: str,
    meta_access_token: str,
    agregar_cta: bool,
    calendly_link: str | None,
) -> ResultadoPublicacion:
    """
    Publica UNA historia en Instagram (media container + publish via Graph
    API). Cualquier fallo de la API se envuelve en ``MetaPublishError``;
    quien llama (Celery/portal) decide como reintentar.
    """
    base = f"{GRAPH_API_BASE}/{instagram_account_id}"
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": meta_access_token,
    }

    if agregar_cta and calendly_link:
        payload["story_cta"] = json.dumps([{
            "type": "SWIPE_UP",
            "param": {"link": calendly_link},
        }])

    try:
        r = requests.post(f"{base}/media", data=payload)
        r.raise_for_status()
        media_id = r.json()["id"]

        r2 = requests.post(f"{base}/media_publish", data={
            "creation_id": media_id,
            "access_token": meta_access_token,
        })
        r2.raise_for_status()
        post_id = r2.json()["id"]
    except Exception as e:
        raise MetaPublishError(f"Error publicando en Instagram: {e}") from e

    return ResultadoPublicacion(ok=True, ig_media_id=post_id)