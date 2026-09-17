"""
Configuración central de Storias.
Todas las variables sensibles vienen del .env — NUNCA hardcodeadas.
"""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # ignora vars desconocidas sin romper
    )

    # ── App ────────────────────────────────────────────────────────────────────
    app_name: str = "Storias"
    environment: str = "development"   # development | production
    secret_key: str                    # para firmar tokens (REQUERIDO)
    allowed_origins: list[str] = ["http://localhost:5001"]

    # ── Supabase ───────────────────────────────────────────────────────────────
    supabase_url: str
    supabase_anon_key: str             # clave pública (safe para el frontend)
    supabase_service_role_key: str     # clave privada — NUNCA al frontend

    # ── Google OAuth ───────────────────────────────────────────────────────────
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:5001/auth/callback"

    # ── Claude API ─────────────────────────────────────────────────────────────
    anthropic_api_key: str

    # ── Cloudinary ─────────────────────────────────────────────────────────────
    # The engine (app/engine/content.py) reads these itself via os.getenv, per
    # its own contract of not depending on this settings module. This copy is
    # for portal-side code (app/services/uploads.py) that isn't part of the
    # engine and should go through Settings like everything else here.
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # ── Meta / Instagram ───────────────────────────────────────────────────────
    # Las credenciales POR CLIENTE se guardan cifradas en Supabase,
    # no en el .env. Acá solo va la app-level config.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_webhook_verify_token: str = ""  # token para verificar webhook de WA

    # ── Encryption key ─────────────────────────────────────────────────────────
    # Usada para cifrar las API keys de clientes en la DB.
    # Generá con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str

    # ── Redis / Celery ─────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    publication_hour: int = Field(default=9, ge=0, le=23)
    publication_minute: int = Field(default=0, ge=0, le=59)
    google_service_account_file: str = ""

    # ── Tokens ─────────────────────────────────────────────────────────────────
    approval_token_ttl_hours: int = 48   # cuánto dura el link de aprobación
    magic_link_ttl_minutes: int = 15     # cuánto dura el link de login cliente

    # ── Rate limiting ──────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 60

    @field_validator("environment")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in ("development", "production"):
            raise ValueError("environment debe ser 'development' o 'production'")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Singleton — se parsea una sola vez al arrancar."""
    return Settings()
