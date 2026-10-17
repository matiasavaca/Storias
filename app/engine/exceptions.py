"""Excepciones tipadas del motor de contenido.

El motor no hace retry ni logging de negocio: levanta la excepcion
correspondiente y quien llama (Celery/portal) decide como reintentar
y loguear.
"""


class EngineError(Exception):
    """Base de todos los errores del motor de contenido."""

    pass


class ClaudeGenerationError(EngineError):
    """Fallo al llamar a la API de Claude o al parsear su respuesta."""

    pass


class ImageProcessingError(EngineError):
    """Fallo al procesar/componer una imagen con Pillow."""

    pass


class MetaPublishError(EngineError):
    """Fallo al publicar en Instagram via Graph API."""

    pass