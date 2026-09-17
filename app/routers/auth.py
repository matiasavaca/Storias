"""
Autenticación — dos flujos:

1. Empleados de agencia → Google OAuth
2. Clientes finales    → Magic link por email (Supabase Auth)
"""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import jwt
from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.config import get_settings, Settings
from app.db.supabase import get_admin_client
from app.services.encryption import encrypt

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_jwt(payload: dict, expires_minutes: int = 60 * 8) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode({**payload, "exp": exp}, s.secret_key, algorithm="HS256")


def _set_session_cookie(response: Response, token: str, s: Settings) -> None:
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,          # inaccesible desde JS — previene XSS
        secure=s.is_production, # solo HTTPS en producción
        samesite="lax",
        max_age=60 * 60 * 8,    # 8 horas
    )


# ── Google OAuth (empleados) ───────────────────────────────────────────────────

@router.get("/google")
async def google_login(request: Request):
    """Inicia el flujo OAuth con Google. Redirige al selector de cuenta."""
    s = get_settings()
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    client = AsyncOAuth2Client(
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        redirect_uri=s.google_redirect_uri,
        scope="openid email profile",
    )
    uri, _ = client.create_authorization_url(
        "https://accounts.google.com/o/oauth2/auth",
        state=state,
        access_type="offline",
        prompt="select_account",
    )
    return RedirectResponse(uri)


@router.get("/callback")
async def google_callback(request: Request, code: str, state: str):
    """Google redirige acá con el código. Creamos la sesión del empleado."""
    s = get_settings()

    # Verificar state para prevenir CSRF
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="State inválido — posible CSRF")
    request.session.pop("oauth_state", None)

    # Intercambiar código por tokens
    async with AsyncOAuth2Client(
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        redirect_uri=s.google_redirect_uri,
    ) as client:
        token_data = await client.fetch_token(
            "https://oauth2.googleapis.com/token", code=code
        )
        userinfo = await client.get("https://www.googleapis.com/oauth2/v3/userinfo")
        userinfo = userinfo.json()

    email: str = userinfo["email"]
    name: str = userinfo.get("name", "").split()[0]

    # Buscar o crear el empleado en Supabase
    db = get_admin_client()
    result = db.table("employees").select("*").eq("email", email).maybe_single().execute()

    # postgrest-py's maybe_single() returns None outright (not a response with
    # data=None) when zero rows match — never assume `result` itself is set.
    if not result or not result.data:
        raise HTTPException(
            status_code=403,
            detail="Este email no tiene acceso a Storias. Contactá a tu agencia.",
        )

    employee = result.data
    token = _make_jwt({
        "sub": employee["id"],
        "email": email,
        "name": name,
        "agency_id": employee["agency_id"],
        "role": employee["role"],
        "team_id": employee.get("team_id"),
    })

    response = RedirectResponse(url="/portal", status_code=302)
    _set_session_cookie(response, token, s)
    return response


# ── Magic link (clientes finales — opción 1) ──────────────────────────────────

@router.post("/magic-link")
async def send_magic_link(email: str):
    """
    El cliente pide acceso a su portal ingresando su email.
    Supabase manda el magic link — nosotros no manejamos contraseñas.
    """
    db = get_admin_client()

    # Verificar que el email pertenece a un cliente registrado
    result = db.table("clients").select("id,agency_id").eq("contact_email", email).maybe_single().execute()
    if not result or not result.data:
        # Respuesta genérica — no revelar si el email existe o no
        return {"detail": "Si tu email está registrado, recibirás el link en breve."}

    # Supabase envía el magic link
    db.auth.sign_in_with_otp({"email": email})
    return {"detail": "Si tu email está registrado, recibirás el link en breve."}


@router.get("/magic-callback")
async def magic_callback(token_hash: str, type: str):
    """Supabase redirige acá cuando el cliente hace clic en el magic link."""
    s = get_settings()
    db = get_admin_client()

    # Verificar el token con Supabase
    session = db.auth.verify_otp({"token_hash": token_hash, "type": type})
    if not session or not session.user:
        raise HTTPException(status_code=400, detail="Link inválido o expirado")

    user = session.user
    client = db.table("clients").select("id,agency_id").eq("contact_email", user.email).maybe_single().execute()
    if not client or not client.data:
        raise HTTPException(status_code=403, detail="Cliente no encontrado")

    our_token = _make_jwt({
        "sub": user.id,
        "email": user.email,
        "client_id": client.data["id"],
        "agency_id": client.data["agency_id"],
        "role": "client",
    }, expires_minutes=60 * 24)  # 24hs para el cliente

    response = RedirectResponse(url="/cliente/portal", status_code=302)
    _set_session_cookie(response, our_token, s)
    return response


# ── Logout ────────────────────────────────────────────────────────────────────

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response
