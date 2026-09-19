"""
Clientes de Supabase.

Hay DOS clientes con permisos distintos:
- anon_client  → permisos de usuario anónimo (respeta RLS)
- admin_client → service_role, bypasea RLS. Solo para operaciones de backend
                 que necesitan acceso total (ej: crear tokens, jobs de Celery).
                 NUNCA exponer al frontend.
"""
from __future__ import annotations
from functools import lru_cache
import httpx
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions
from app.config import get_settings

# One lru_cache'd Client per process means its underlying httpx client is
# shared across every FastAPI request thread. With HTTP/2 (the default when
# the `h2` package is installed) that shared connection gets multiplexed
# across threads, which on Windows surfaces as intermittent
# "WinError 10035 - non-blocking socket operation could not be completed
# immediately" — requests either 500 or hang forever with no timeout. Forcing
# HTTP/1.1 avoids the multiplexed-stream contention; the explicit timeout
# turns a hang into a clear, fast error instead of an infinite spinner.
def _http_client() -> httpx.Client:
    return httpx.Client(http2=False, timeout=20)


@lru_cache
def get_anon_client() -> Client:
    """Cliente con la clave pública. Respeta Row Level Security."""
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key,
        options=SyncClientOptions(httpx_client=_http_client()))


@lru_cache
def get_admin_client() -> Client:
    """
    Cliente con service_role key. Bypasea RLS.
    Usar SOLO en operaciones de servidor confiables.
    NUNCA pasar este cliente a código que el usuario pueda influenciar.
    """
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key,
        options=SyncClientOptions(httpx_client=_http_client()))
