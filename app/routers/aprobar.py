"""
Opción 3 — Aprobación por link de WhatsApp.

Flujo:
  1. Empleado llama a POST /aprobar/generar  → crea token en DB, manda WA
  2. Cliente abre GET  /aprobar/<token>      → ve la página mobile
  3. Cliente llama a  POST /aprobar/<token>  → marca aprobado, programa publicación
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.deps import EmployeeDep
from app.services import whatsapp, scheduler

router = APIRouter(prefix="/aprobar", tags=["aprobación"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class GenerarLinkRequest(BaseModel):
    client_id: str
    story_group_id: str


class AprobarRequest(BaseModel):
    story_ids: list[str]          # ids de las historias que aprueba
    comentario: str | None = None


# ── Generar link (solo empleados) ─────────────────────────────────────────────

@router.post("/generar", status_code=201)
async def generar_link(body: GenerarLinkRequest, employee: EmployeeDep):
    """
    Crea un token de aprobación y lo manda por WhatsApp al cliente.
    Solo empleados autenticados pueden llamar a esto.
    """
    s = get_settings()
    db = get_admin_client()

    # Verificar que el cliente pertenece a la misma agencia del empleado
    client = (
        db.table("clients")
        .select("id,name,contact_name,wa_phone_encrypted,agency_id")
        .eq("id", body.client_id)
        .eq("agency_id", employee.agency_id)  # ← seguridad: no puede acceder a clientes de otra agencia
        .maybe_single()
        .execute()
    )
    if not client.data:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Verificar que el story_group pertenece al cliente
    group = (
        db.table("story_groups")
        .select("id,scheduled_date,scheduled_time")
        .eq("id", body.story_group_id)
        .eq("client_id", body.client_id)
        .maybe_single()
        .execute()
    )
    if not group.data:
        raise HTTPException(status_code=404, detail="Grupo de historias no encontrado")

    # Invalidar tokens anteriores del mismo grupo (si el empleado reenvía)
    db.table("approval_tokens").update({"invalidated_at": datetime.now(timezone.utc).isoformat()}).eq(
        "story_group_id", body.story_group_id
    ).is_("invalidated_at", "null").execute()

    # Crear nuevo token
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=s.approval_token_ttl_hours)
    db.table("approval_tokens").insert({
        "token": token,
        "story_group_id": body.story_group_id,
        "client_id": body.client_id,
        "agency_id": employee.agency_id,
        "created_by": employee.id,
        "expires_at": expires_at.isoformat(),
    }).execute()

    # Mandar WhatsApp
    approval_url = f"https://storias.app/aprobar/{token}"  # en dev: localhost
    if s.environment == "development":
        approval_url = f"http://localhost:5001/aprobar/{token}"

    await whatsapp.send_approval_message(
        client_data=client.data,
        group_data=group.data,
        approval_url=approval_url,
    )

    return {"token": token, "expires_at": expires_at.isoformat(), "url": approval_url}


# ── Ver página de aprobación (público, solo con token válido) ─────────────────

_SCRATCHPAD = Path(__file__).parent.parent.parent / "scratchpad"


@router.get("/{token}", response_class=HTMLResponse)
async def ver_aprobacion(token: str, request: Request):
    """Página mobile que ve el cliente. No requiere login."""
    s = get_settings()

    # En dev servimos el HTML estático directamente (sin DB)
    if not s.is_production:
        p = _SCRATCHPAD / "aprobar.html"
        if p.exists():
            return FileResponse(str(p), media_type="text/html")
        raise HTTPException(status_code=404, detail="aprobar.html no encontrado en scratchpad")

    # En producción validamos el token contra la DB
    db = get_admin_client()
    aprobacion = _get_valid_token(db, token)

    stories = (
        db.table("stories")
        .select("id,order,text,image_url")
        .eq("story_group_id", aprobacion["story_group_id"])
        .order("order")
        .execute()
    )
    client = (
        db.table("clients")
        .select("name,contact_name")
        .eq("id", aprobacion["client_id"])
        .single()
        .execute()
    )
    group = (
        db.table("story_groups")
        .select("scheduled_date,scheduled_time")
        .eq("id", aprobacion["story_group_id"])
        .single()
        .execute()
    )

    from jinja2 import Environment, FileSystemLoader
    _tmpl_dir = Path(__file__).parent.parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(_tmpl_dir)), autoescape=True)
    html = env.get_template("aprobar.html").render(
        token=token,
        client=client.data,
        group=group.data,
        stories=stories.data,
        expires_at=aprobacion["expires_at"],
    )
    return HTMLResponse(html)


# ── Confirmar aprobación (público, solo con token válido) ─────────────────────

@router.post("/{token}")
async def confirmar_aprobacion(token: str, body: AprobarRequest):
    """El cliente aprieta 'Aprobar'. Marca el token como usado y programa la publicación."""
    db = get_admin_client()
    aprobacion = _get_valid_token(db, token)

    now = datetime.now(timezone.utc).isoformat()

    # Marcar token como usado (no se puede usar dos veces)
    db.table("approval_tokens").update({
        "used_at": now,
        "approved_story_ids": body.story_ids,
        "comentario": body.comentario,
    }).eq("token", token).execute()

    # Marcar historias como aprobadas
    db.table("stories").update({"approved_at": now}).in_("id", body.story_ids).execute()

    # Marcar el grupo como aprobado si todas las historias fueron aprobadas
    total = db.table("stories").select("id", count="exact").eq(
        "story_group_id", aprobacion["story_group_id"]
    ).execute()
    if len(body.story_ids) >= total.count:
        db.table("story_groups").update({"status": "approved", "approved_at": now}).eq(
            "id", aprobacion["story_group_id"]
        ).execute()
        # Encolar la publicación en Celery
        scheduler.schedule_publication.delay(aprobacion["story_group_id"])

    return {"detail": "Aprobado correctamente"}


# ── Helper interno ────────────────────────────────────────────────────────────

def _get_valid_token(db, token: str) -> dict:
    """Valida que el token exista, no haya expirado y no haya sido usado."""
    result = db.table("approval_tokens").select("*").eq("token", token).maybe_single().execute()

    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Link no encontrado")

    t = result.data
    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(t["expires_at"])

    if t.get("invalidated_at"):
        raise HTTPException(status_code=410, detail="Este link fue reemplazado por uno nuevo")
    if t.get("used_at"):
        raise HTTPException(status_code=410, detail="Este link ya fue usado")
    if now > expires:
        raise HTTPException(status_code=410, detail="Link expirado. Pedile a la agencia que te envíe uno nuevo")

    return t
