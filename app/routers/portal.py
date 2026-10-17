"""Authenticated API used by the employee portal."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
import re

import requests
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.deps import AdminDep, EmployeeDep
from app.engine import content
from app.engine.exceptions import ClaudeGenerationError, EngineError
from app.engine.imaging import _FONT_FILES, FONT_CHOICES
from app.engine.schemas import ImagenCandidata
from app.services import content_jobs, drive, uploads
from app.services.content_jobs import PUBLISH_DAY_OFFSETS, build_content_config

router = APIRouter(prefix="/portal", tags=["portal"])
logger = logging.getLogger(__name__)

# Stories in these states already happened (or are mid-flight) on Instagram:
# editing or cancelling them would silently diverge the DB from what's live.
_LOCKED_STATES = {"generando", "publicando", "publicado", "cancelada"}

_CLIENT_DETAIL = (
    "id,agency_id,name,business_description,weekly_focus,"
    "weekly_focus_expires_at,tone_examples,topics,drive_folder_id,logo_url,"
    "avatar_url,avatar_public_id,instagram_profile_url,whatsapp_contact,"
    "contact_email,calendly_link,prob_link,generation_error,"
    "generation_error_at,publish_days,"
    "publish_together,font_choice"
)


class ClientPatch(BaseModel):
    business_description: str | None = None
    weekly_focus: str | None = None
    weekly_focus_expires_at: date | None = None
    tone_examples: list[list[str]] | None = None
    topics: list[str] | None = None

    @field_validator("tone_examples", mode="before")
    @classmethod
    def tone_examples_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("tone_examples no puede ser null")
        return value


class ClientPmPatch(BaseModel):
    employee_id: str | None


class ScheduleEntry(BaseModel):
    day: int = Field(ge=0, le=6)
    time: str
    count: int | None = Field(default=None, ge=1, le=4)

    @field_validator("time")
    @classmethod
    def valid_hhmm(cls, value):
        if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit() \
                or not (0 <= int(value[:2]) <= 23) or not (0 <= int(value[3:]) <= 59):
            raise ValueError("time debe tener formato HH:MM (24hs)")
        return value


class ClientRitmoPatch(BaseModel):
    publish_days: list[ScheduleEntry] | None = None

    @field_validator("publish_days")
    @classmethod
    def one_to_four_distinct_weekdays(cls, value):
        if value is None:
            return None
        days = [entry.day for entry in value]
        if not 1 <= len(value) <= 4 or len(set(days)) != len(value):
            raise ValueError("publish_days debe tener entre 1 y 4 días distintos (0=lunes..6=domingo)")
        counts = [entry.count for entry in value]
        if any(count is not None for count in counts):
            if any(count is None for count in counts) or sum(counts) != 4:
                raise ValueError(
                    "Si se especifica count en algún día, todos los días deben traer count "
                    "y la suma tiene que dar 4 (una historia por cada una de las 4 del hilo)."
                )
        return sorted(value, key=lambda entry: entry.day)


_DRIVE_FOLDER_URL_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")


class BulkClientEntry(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    drive_folder_id: str = Field(min_length=1)
    business_description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("drive_folder_id", mode="before")
    @classmethod
    def extract_folder_id(cls, value):
        """Accept a Drive folder ID or the complete folder URL."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        match = _DRIVE_FOLDER_URL_RE.search(value)
        return match.group(1) if match else value


class BulkClientsRequest(BaseModel):
    # Validate the batch envelope here and each row in the endpoint.  That
    # lets a malformed row return its own result instead of rejecting every
    # otherwise valid client in the upload.
    clientes: list[object] = Field(min_length=1, max_length=300)


class StoryPatch(BaseModel):
    texto_nuevo: str = Field(min_length=1)


class GenerateStoryRequest(BaseModel):
    fecha_publicacion: str
    hora_publicacion: str


class StoryOrder(BaseModel):
    story_id: str
    nuevo_order: int = Field(ge=1, le=10)


class ReorderRequest(BaseModel):
    historias: list[StoryOrder] = Field(min_length=1)


def _client_or_error(db, client_id: str, agency_id: str) -> dict:
    result = db.table("clients").select(_CLIENT_DETAIL).eq("id", client_id).maybe_single().execute()
    # postgrest-py's maybe_single() returns None outright (not a response with
    # data=None) when zero rows match — never assume `result` itself is set.
    if not result or not result.data:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if result.data["agency_id"] != agency_id:
        raise HTTPException(status_code=403, detail="Cliente fuera de la agencia")
    return result.data


@router.get("/me")
def get_me(employee: EmployeeDep):
    return {"id": employee.id, "name": employee.name, "email": employee.email,
            "role": employee.role, "agency_id": employee.agency_id}


@router.post("/clientes/alta-masiva")
def create_clients_bulk(body: BulkClientsRequest, employee: AdminDep):
    """Create each supplied client independently, reporting one result per row."""
    db = get_admin_client()
    existing_names = {
        row["name"].strip().lower()
        for row in db.table("clients").select("name").eq(
            "agency_id", employee.agency_id
        ).execute().data or []
    }

    resultados = []
    seen_in_batch: set[str] = set()
    for i, raw_entry in enumerate(body.clientes, start=1):
        try:
            entry = BulkClientEntry.model_validate(raw_entry)
        except ValidationError:
            name = raw_entry.get("name", "") if isinstance(raw_entry, dict) else ""
            resultados.append({
                "fila": i,
                "name": name.strip() if isinstance(name, str) else "",
                "status": "error",
                "motivo": "Datos inválidos: revisá nombre y carpeta de Drive.",
            })
            continue
        key = entry.name.lower()
        if key in existing_names or key in seen_in_batch:
            resultados.append({
                "fila": i, "name": entry.name, "status": "error",
                "motivo": "Ya existe un cliente con ese nombre.",
            })
            continue
        payload = {
            "agency_id": employee.agency_id,
            "name": entry.name,
            "drive_folder_id": entry.drive_folder_id,
            "business_description": entry.business_description or "",
            "active": True,
        }
        try:
            created = db.table("clients").insert(payload).execute().data
        except APIError as exc:
            logger.error("Bulk client insert failed for %r: %s", entry.name, exc)
            resultados.append({
                "fila": i, "name": entry.name, "status": "error",
                "motivo": "No se pudo crear: error de base de datos.",
            })
            continue
        seen_in_batch.add(key)
        resultados.append({
            "fila": i, "name": entry.name, "status": "creado",
            "client_id": created[0]["id"],
        })
    return {"resultados": resultados}


@router.get("/clientes")
def list_clients(employee: EmployeeDep, solo_mios: bool = False):
    db = get_admin_client()
    query = db.table("clients").select(_CLIENT_DETAIL).eq("agency_id", employee.agency_id)
    if solo_mios:
        assignments = db.table("employee_clients").select("client_id").eq(
            "employee_id", employee.id
        ).execute().data or []
        client_ids = [row["client_id"] for row in assignments]
        if not client_ids:
            return []
        query = query.in_("id", client_ids)
    clients = query.order("name").execute().data or []
    if clients:
        ids = [c["id"] for c in clients]
        rows = db.table("stories").select("client_id,aprobado,estado").in_("client_id", ids).neq(
            "estado", "cancelada"
        ).neq(
            "estado", "generando"
        ).gte("fecha_publicacion", date.today().isoformat()).execute().data or []
        counts: dict[str, int] = {}
        pending: dict[str, int] = {}
        for row in rows:
            counts[row["client_id"]] = counts.get(row["client_id"], 0) + 1
            if not row.get("aprobado") and row.get("estado") not in ("publicando", "publicado"):
                pending[row["client_id"]] = pending.get(row["client_id"], 0) + 1
        for c in clients:
            c["stories_count"] = counts.get(c["id"], 0)
            c["pending_count"] = pending.get(c["id"], 0)
    return clients


_UPCOMING_DAYS = 7
_UPCOMING_LIMIT = 10


@router.get("/resumen")
def get_summary(employee: EmployeeDep):
    """Agency-wide snapshot for the Inicio tab: a publish funnel — en edición
    (not approved yet) → agendadas (approved, ready to go out) → publicadas —
    plus workload and coverage stats. The upcoming-stories query (active,
    non-cancelled, fecha_publicacion >= today) is the same definition
    list_clients already uses for its per-client counter, split here by
    aprobado into "en edición" vs "agendadas" so these numbers always agree
    with what an employee sees per-client — no separate metric to drift."""
    db = get_admin_client()
    clients = db.table("clients").select("id,name").eq(
        "agency_id", employee.agency_id
    ).execute().data or []
    if not clients:
        return {
            "historias_publicadas": 0, "historias_en_edicion": 0, "historias_agendadas": 0,
            "clientes_count": 0, "promedio_por_cliente": 0, "aprobacion_pct": None,
            "clientes_sin_actividad": [], "proximas_publicaciones": [],
        }

    client_ids = [c["id"] for c in clients]
    published = db.table("stories").select("id").in_("client_id", client_ids).eq(
        "estado", "publicado"
    ).execute().data or []
    upcoming = db.table("stories").select("client_id,aprobado,fecha_publicacion,hora_publicacion").in_(
        "client_id", client_ids
    ).neq("estado", "cancelada").neq("estado", "generando").gte(
        "fecha_publicacion", date.today().isoformat()
    ).execute().data or []

    by_client: dict[str, list[bool]] = {}
    for row in upcoming:
        by_client.setdefault(row["client_id"], []).append(bool(row["aprobado"]))
    total_upcoming = len(upcoming)
    total_agendadas = sum(1 for row in upcoming if row["aprobado"])
    total_en_edicion = total_upcoming - total_agendadas

    # "Próximas publicaciones": the same upcoming rows grouped by client and
    # day, limited to the next _UPCOMING_DAYS days and capped at _UPCOMING_LIMIT.
    names_by_id = {c["id"]: c["name"] for c in clients}
    horizon = (date.today() + timedelta(days=_UPCOMING_DAYS)).isoformat()
    days: dict[tuple[str, str], dict] = {}
    for row in upcoming:
        fecha = row.get("fecha_publicacion")
        if not fecha or fecha > horizon:
            continue
        entry = days.setdefault((row["client_id"], fecha), {
            "client_id": row["client_id"], "client_name": names_by_id.get(row["client_id"], "?"),
            "fecha": fecha, "hora": None, "total": 0, "aprobadas": 0,
        })
        entry["total"] += 1
        entry["aprobadas"] += 1 if row["aprobado"] else 0
        hora = (row.get("hora_publicacion") or "")[:5]
        if hora and (entry["hora"] is None or hora < entry["hora"]):
            entry["hora"] = hora
    proximas = sorted(
        days.values(),
        key=lambda item: (item["fecha"], item["hora"] or "99:99", item["client_name"].lower()),
    )[:_UPCOMING_LIMIT]

    return {
        "historias_publicadas": len(published),
        "historias_en_edicion": total_en_edicion,
        "historias_agendadas": total_agendadas,
        "clientes_count": len(clients),
        "promedio_por_cliente": round(total_upcoming / len(clients), 1),
        "aprobacion_pct": round(total_agendadas / total_upcoming * 100, 1) if total_upcoming else None,
        # A client with nothing upcoming (approved or not) is the one that
        # needs attention right now, regardless of how much it published before.
        "clientes_sin_actividad": [
            {"id": c["id"], "name": c["name"]} for c in clients if not by_client.get(c["id"])
        ],
        "proximas_publicaciones": proximas,
    }


@router.get("/salud")
def get_health(employee: EmployeeDep):
    """Return agency-wide signals that otherwise require inspecting clients one by one."""
    db = get_admin_client()
    clients = db.table("clients").select(
        "id,name,generation_error,generation_error_at,pool_bajo_at"
    ).eq("agency_id", employee.agency_id).execute().data or []
    if not clients:
        return {
            "clientes_con_error_generacion": [],
            "clientes_con_pool_bajo": [],
            "clientes_con_historias_en_error": [],
        }

    con_error_generacion = sorted(
        (
            {
                "id": client["id"], "name": client["name"],
                "generation_error": client["generation_error"],
                "generation_error_at": client["generation_error_at"],
            }
            for client in clients if client.get("generation_error")
        ),
        key=lambda client: client["generation_error_at"] or "",
    )
    con_pool_bajo = sorted(
        (
            {
                "id": client["id"], "name": client["name"],
                "pool_bajo_at": client["pool_bajo_at"],
            }
            for client in clients if client.get("pool_bajo_at")
        ),
        key=lambda client: client["pool_bajo_at"] or "",
    )

    client_ids = [client["id"] for client in clients]
    names_by_id = {client["id"]: client["name"] for client in clients}
    failed_stories = db.table("stories").select("client_id,fecha_publicacion").in_(
        "client_id", client_ids
    ).eq("estado", "error").execute().data or []
    by_client: dict[str, list[str]] = {}
    for row in failed_stories:
        by_client.setdefault(row["client_id"], []).append(row.get("fecha_publicacion") or "")
    con_historias_en_error = sorted(
        (
            {
                "id": client_id, "name": names_by_id.get(client_id, "?"),
                "historias_en_error": len(fechas),
                "fecha_mas_antigua": min(fechas) if fechas else None,
            }
            for client_id, fechas in by_client.items()
        ),
        key=lambda client: client["fecha_mas_antigua"] or "",
    )

    return {
        "clientes_con_error_generacion": con_error_generacion,
        "clientes_con_pool_bajo": con_pool_bajo,
        "clientes_con_historias_en_error": con_historias_en_error,
    }


@router.get("/empleados")
def list_employees(employee: EmployeeDep):
    """Employees available to assign to clients in this agency."""
    db = get_admin_client()
    return db.table("employees").select("id,name,email").eq(
        "agency_id", employee.agency_id
    ).order("name").execute().data or []


@router.get("/clientes/{client_id}")
def get_client(client_id: str, employee: EmployeeDep):
    db = get_admin_client()
    client = _client_or_error(db, client_id, employee.agency_id)
    assignment = db.table("employee_clients").select("employee_id").eq(
        "client_id", client_id
    ).maybe_single().execute()
    return {**client, "assigned_employee_id": assignment.data.get("employee_id") if assignment and assignment.data else None}


@router.patch("/clientes/{client_id}/pm")
def patch_client_pm(client_id: str, body: ClientPmPatch, employee: EmployeeDep):
    """Qué PM lleva este cliente — cualquier empleado puede reasignarlo.
    Upsert atómico sobre employee_clients (UNIQUE en client_id) en vez de
    delete+insert: dos reasignaciones concurrentes del mismo cliente nunca
    pueden dejar dos filas, porque no hay ventana entre borrar e insertar."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    if body.employee_id is not None:
        target = db.table("employees").select("id").eq("id", body.employee_id).eq(
            "agency_id", employee.agency_id
        ).maybe_single().execute()
        if not target or not target.data:
            raise HTTPException(status_code=422, detail="Empleado no encontrado en tu agencia")
        db.table("employee_clients").upsert(
            {"employee_id": body.employee_id, "client_id": client_id},
            on_conflict="client_id",
        ).execute()
    else:
        db.table("employee_clients").delete().eq("client_id", client_id).execute()
    return {"client_id": client_id, "employee_id": body.employee_id}


@router.get("/clientes/{client_id}/drive-info")
def get_drive_info(client_id: str, employee: EmployeeDep):
    """Metadata-only count of images in the client's Drive folder.

    Best-effort: Drive access needs a service account file that isn't
    always configured in every environment, so failures return count=None
    instead of a 500 — this is informational, not a required feature."""
    client = _client_or_error(get_admin_client(), client_id, employee.agency_id)
    folder_id = client.get("drive_folder_id")
    if not folder_id:
        return {"count": None}
    try:
        return {"count": drive.count_images(folder_id)}
    except Exception:
        return {"count": None}


@router.patch("/clientes/{client_id}")
def patch_client(client_id: str, body: ClientPatch, employee: EmployeeDep):
    db = get_admin_client()
    current = _client_or_error(db, client_id, employee.agency_id)
    supplied = body.model_dump(mode="json", exclude_unset=True)
    changes = {key: value for key, value in supplied.items() if current.get(key) != value}
    if not changes:
        return current

    updated = db.rpc("update_client_prompt", {
        "p_client_id": client_id, "p_employee_id": employee.id,
        "p_agency_id": employee.agency_id, "p_patch": changes,
    }).execute().data
    return updated or {**current, **changes}


@router.get("/clientes/{client_id}/historial")
def list_prompt_history(client_id: str, employee: EmployeeDep):
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    rows = db.table("prompt_history").select(
        "id,field,old_value,new_value,changed_at,changed_by,employees(name)"
    ).eq("client_id", client_id).order("changed_at", desc=True).limit(50).execute().data or []
    for row in rows:
        row["changed_by_name"] = (row.pop("employees", None) or {}).get("name")
    return rows



@router.get("/tipografias")
def list_font_choices(employee: EmployeeDep):
    # "file" points at the same bundled .ttf app.engine.imaging composes
    # with, served read-only under /fonts, so the portal can preview each
    # option in its own real typeface instead of just naming it.
    return [
        {"key": key, "label": label, "file": _FONT_FILES[key]}
        for key, label in FONT_CHOICES.items()
    ]


class ClientContactPatch(BaseModel):
    instagram_profile_url: str | None = None
    whatsapp_contact: str | None = None
    contact_email: str | None = None


class ClientFontPatch(BaseModel):
    font_choice: str | None = None

    @field_validator("font_choice")
    @classmethod
    def known_font(cls, value):
        if value is not None and value not in FONT_CHOICES:
            raise ValueError("Tipografía no reconocida")
        return value


@router.patch("/clientes/{client_id}/tipografia")
def patch_client_font(client_id: str, body: ClientFontPatch, employee: EmployeeDep):
    """Which bundled font the AI composes onto this client's Story images —
    purely stylistic, so a plain update instead of the audited RPC."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    updated = db.table("clients").update({"font_choice": body.font_choice}).eq(
        "id", client_id
    ).execute().data
    return updated[0] if isinstance(updated, list) and updated else {"id": client_id, "font_choice": body.font_choice}


@router.patch("/clientes/{client_id}/contacto")
def patch_client_contact(client_id: str, body: ClientContactPatch, employee: EmployeeDep):
    """Save organizational contact details without changing editorial prompt data."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    changes = body.model_dump(mode="json", exclude_unset=True)
    if not changes:
        return {"id": client_id}
    updated = db.table("clients").update(changes).eq("id", client_id).execute().data
    return updated[0] if isinstance(updated, list) and updated else {"id": client_id, **changes}


@router.post("/clientes/{client_id}/avatar")
async def upload_client_avatar(client_id: str, employee: EmployeeDep, image: UploadFile = File(...)):
    """Upload a portal-only avatar; it remains separate from the content logo."""
    db = get_admin_client()
    current = _client_or_error(db, client_id, employee.agency_id)
    data = await image.read()
    try:
        uploaded = uploads.upload_image(data, client_id, "avatar")
    except uploads.UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        updated = db.table("clients").update(
            {"avatar_url": uploaded.url, "avatar_public_id": uploaded.public_id}
        ).eq("id", client_id).execute().data
        if not updated:
            raise RuntimeError("No se pudo guardar el avatar")
    except Exception:
        try:
            uploads.delete_image(uploaded.public_id)
        except uploads.UploadError:
            pass
        raise
    old_public_id = current.get("avatar_public_id")
    if old_public_id and old_public_id != uploaded.public_id:
        try:
            uploads.delete_image(old_public_id)
        except uploads.UploadError:
            pass
    return updated[0]


@router.patch("/clientes/{client_id}/ritmo")
def patch_client_ritmo(client_id: str, body: ClientRitmoPatch, employee: EmployeeDep):
    """Save weekdays, time and count for the client's four weekly stories."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    payload = {}
    if body.publish_days is not None:
        payload["publish_days"] = [entry.model_dump() for entry in body.publish_days]
    if not payload:
        raise HTTPException(status_code=400, detail="Nada para actualizar")
    updated = db.table("clients").update(payload).eq(
        "id", client_id
    ).execute().data
    return updated[0] if isinstance(updated, list) and updated else {"id": client_id, **payload}


@router.get("/ritmo-default")
def get_default_ritmo(employee: EmployeeDep):
    settings = get_settings()
    default_time = f"{settings.publication_hour:02d}:{settings.publication_minute:02d}"
    return {"publish_days": [{"day": day, "time": default_time, "count": 1}
                             for day in PUBLISH_DAY_OFFSETS]}


@router.post("/clientes/{client_id}/generar-semana")
def generar_semana(client_id: str, employee: EmployeeDep):
    """Generate this client's upcoming weekly thread immediately."""
    db = get_admin_client()
    client = _client_or_error(db, client_id, employee.agency_id)
    try:
        result = content_jobs.generate_for_client(db, client, content_jobs.local_today())
    except Exception as exc:
        try:
            db.table("clients").update({
                "generation_error": str(exc),
                "generation_error_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", client_id).execute()
        except Exception:
            logger.exception("Could not persist generation error for client %s", client_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not result["created"]:
        return {"detail": "Ya se generó contenido para esta semana.", "created": False}
    return {
        "detail": "Se generaron 4 historias para la semana que viene.",
        "created": True,
        "recycled": result["recycled"],
    }


@router.post("/clientes/{client_id}/probar-prompt")
def try_prompt(client_id: str, employee: EmployeeDep):
    db = get_admin_client()
    client = _client_or_error(db, client_id, employee.agency_id)
    image = drive.first_image(client.get("drive_folder_id"))
    if not image:
        raise HTTPException(status_code=422, detail="El cliente no tiene imágenes disponibles")
    image_id, image_name, image_bytes = image
    candidate = ImagenCandidata(
        drive_file_id=image_id, drive_file_name=image_name, image_bytes=image_bytes,
    )
    return {"historias": content.generar_texto_de_prueba(build_content_config(client), candidate)}


@router.get("/clientes/{client_id}/historias")
def list_stories(client_id: str, employee: EmployeeDep):
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    groups = db.table("story_groups").select("*,stories(*)").eq("client_id", client_id).gte(
        "scheduled_date", date.today().isoformat()
    ).order("scheduled_date").execute().data or []
    for group in groups:
        group["stories"] = [
            story for story in group.get("stories") or []
            if story.get("estado") not in {"cancelada", "generando"}
        ]
    return groups


def _valid_hhmm(value: str) -> bool:
    return len(value) == 5 and value[2] == ":" and value[:2].isdigit() and value[3:].isdigit() \
        and 0 <= int(value[:2]) <= 23 and 0 <= int(value[3:]) <= 59


@router.post("/clientes/{client_id}/historias/manual")
async def create_manual_story(client_id: str, employee: EmployeeDep,
    fecha_publicacion: str = Form(...), hora_publicacion: str = Form(...),
    image: UploadFile = File(...)):
    """Manually schedule one image as a Story on a specific date — independent
    of the AI weekly generation. Adding a second image to a date that already
    has one just adds another story alongside it (each still publishes as its
    own separate Instagram Story; the platform has no multi-image Story)."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    try:
        parsed_date = date.fromisoformat(fecha_publicacion)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha inválida")
    if not _valid_hhmm(hora_publicacion):
        raise HTTPException(status_code=422, detail="Hora inválida (formato HH:MM)")

    group = db.table("story_groups").select("id,agendado").eq("client_id", client_id).eq(
        "scheduled_date", fecha_publicacion
    ).is_("generation_week", "null").is_("manual_duplicate_of", "null").execute().data
    created_group = False
    if group:
        if group[0]["agendado"]:
            raise HTTPException(
                status_code=409,
                detail="Ya existe un grupo manual agendado para ese cliente y fecha.",
            )
        group_id = group[0]["id"]
        existing = db.table("stories").select("order").eq(
            "story_group_id", group_id
        ).order("order", desc=True).limit(1).execute().data
        next_order = (existing[0]["order"] + 1) if existing else 1
        if next_order > 10:
            raise HTTPException(status_code=422, detail="Ya hay demasiadas historias en este día")
    else:
        try:
            created = db.table("story_groups").insert({
                "client_id": client_id, "agency_id": employee.agency_id,
                "scheduled_date": fecha_publicacion, "scheduled_time": f"{hora_publicacion}:00",
                "status": "pending",
            }).execute().data
        except APIError as exc:
            if exc.code == "23505":
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe un grupo manual para ese cliente y fecha. Recargá y probá de nuevo.",
                ) from exc
            raise
        group_id = created[0]["id"]
        next_order = 1
        created_group = True

    data = await image.read()
    try:
        uploaded = uploads.upload_image(data, client_id, f"{fecha_publicacion}-{parsed_date.toordinal()}-{hora_publicacion.replace(':','')}")
    except uploads.UploadError as exc:
        if created_group:
            _delete_manual_group_if_empty(db, group_id)
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        story = db.table("stories").insert({
            "story_group_id": group_id, "client_id": client_id, "order": next_order,
            "text": "", "image_url": uploaded.url, "image_original_url": uploaded.url,
            "fecha_publicacion": fecha_publicacion, "hora_publicacion": f"{hora_publicacion}:00",
            "estado": "pendiente", "agregar_cta": False, "aprobado": False,
        }).execute().data
        if not story:
            raise RuntimeError("No se pudo guardar la historia manual")
    except Exception:
        try:
            uploads.delete_image(uploaded.public_id)
        except uploads.UploadError:
            pass
        if created_group:
            _delete_manual_group_if_empty(db, group_id)
        raise
    return story[0]


def _delete_manual_group_if_empty(db, group_id: str) -> None:
    """Atomically remove a failed reservation only while it has no stories."""
    try:
        db.rpc("delete_empty_manual_group", {"p_group_id": group_id}).execute()
    except Exception:
        # Cleanup must not hide the original upload/database failure.
        pass


@router.post("/clientes/{client_id}/historias/generar")
def generate_story_for_day(client_id: str, body: GenerateStoryRequest, employee: EmployeeDep):
    """Generate one scheduled Story from the client's Drive pool.

    A short database reservation claims the next position before calling Claude
    or Cloudinary. The reservation is a transient ``generando`` story, so
    concurrent requests cannot spend resources for the same slot.
    """
    db = get_admin_client()
    client = _client_or_error(db, client_id, employee.agency_id)
    try:
        parsed_date = date.fromisoformat(body.fecha_publicacion)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha inválida")
    if not _valid_hhmm(body.hora_publicacion):
        raise HTTPException(status_code=422, detail="Hora inválida (formato HH:MM)")

    group = db.table("story_groups").select("id,agendado").eq("client_id", client_id).eq(
        "scheduled_date", body.fecha_publicacion
    ).is_("generation_week", "null").is_("manual_duplicate_of", "null").execute().data
    created_group = False
    if group:
        group_id = group[0]["id"]
    else:
        try:
            created = db.table("story_groups").insert({
                "client_id": client_id,
                "agency_id": employee.agency_id,
                "scheduled_date": body.fecha_publicacion,
                "scheduled_time": f"{body.hora_publicacion}:00",
                "status": "pending",
            }).execute().data
            group_id = created[0]["id"]
            created_group = True
        except APIError as exc:
            if exc.code != "23505":
                raise
            # Another request created this day's group between our read and
            # insert. Reuse it; the reservation RPC validates it under lock.
            raced_group = db.table("story_groups").select("id").eq(
                "client_id", client_id
            ).eq("scheduled_date", body.fecha_publicacion).is_(
                "generation_week", "null"
            ).is_("manual_duplicate_of", "null").execute().data or []
            if not raced_group:
                raise
            group_id = raced_group[0]["id"]

    try:
        reservation = db.rpc("reserve_generated_story", {
            "p_group_id": group_id,
            "p_client_id": client_id,
            "p_agency_id": employee.agency_id,
            "p_fecha_publicacion": body.fecha_publicacion,
            "p_hora_publicacion": f"{body.hora_publicacion}:00",
        }).execute().data
        if not reservation:
            raise RuntimeError("No se pudo reservar una posición para la historia")
    except Exception as exc:
        if created_group:
            _delete_manual_group_if_empty(db, group_id)
        if isinstance(exc, APIError):
            raise HTTPException(
                status_code=409,
                detail="No se puede generar una historia para este día. Recargá y probá de nuevo.",
            ) from exc
        raise

    reservation_id = reservation["id"]
    next_order = reservation["order"]

    def release_reservation() -> None:
        try:
            db.rpc("release_reserved_generated_story", {
                "p_story_id": reservation_id,
            }).execute()
        except Exception:
            logger.exception("No se pudo liberar la reserva de historia %s", reservation_id)
        if created_group:
            _delete_manual_group_if_empty(db, group_id)

    try:
        history = db.table("client_images").select("drive_file_id,last_used_at").eq(
            "client_id", client_id
        ).execute().data or []
        available = drive.list_image_metadata(client.get("drive_folder_id"))
        if not available:
            raise HTTPException(status_code=422, detail="El cliente no tiene imágenes disponibles en Drive")
        now = datetime.now(timezone.utc)
        ranked, _ = content_jobs.seleccionar_imagenes(available, history, now, limite=None)
        downloaded = drive.download_images(ranked, limit=1)
        if not downloaded:
            raise HTTPException(status_code=422, detail="No se pudo descargar ninguna imagen legible de Drive")
        image_id, image_name, image_bytes = downloaded[0]

        config = build_content_config(client)
        text = content.generar_texto_para_imagen(config, image_bytes)
        imagen_editada = content.editar_historia(
            config, image_bytes, text, next_order, font_choice=client.get("font_choice"),
        )
    except Exception as exc:
        release_reservation()
        if isinstance(exc, EngineError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise

    try:
        uploaded = uploads.upload_image(
            image_bytes, client_id,
            f"{body.fecha_publicacion}-{parsed_date.toordinal()}-"
            f"{body.hora_publicacion.replace(':', '')}-ia",
        )
    except Exception as exc:
        try:
            uploads.delete_image(imagen_editada.public_id)
        except Exception:
            logger.exception("No se pudo borrar el compuesto huérfano %s", imagen_editada.public_id)
        release_reservation()
        if isinstance(exc, uploads.UploadError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise

    try:
        story = db.rpc("finalize_reserved_generated_story", {
            "p_story_id": reservation_id,
            "p_story": {
                "client_id": client_id,
                "text": text,
                "image_url": imagen_editada.url,
                "image_original_url": uploaded.url,
                "fecha_publicacion": body.fecha_publicacion,
                "hora_publicacion": f"{body.hora_publicacion}:00",
                "estado": "pendiente",
                "agregar_cta": False,
                "aprobado": False,
            },
            "p_image": {
                "drive_file_id": image_id,
                "drive_file_name": image_name,
            },
        }).execute().data
        if not story:
            raise RuntimeError("No se pudo guardar la historia generada")
    except Exception:
        # A transport failure can happen after PostgREST has committed the
        # RPC. Reconcile before compensating: deleting assets in that case
        # would leave a successfully saved Story with broken URLs.
        try:
            result = db.table("stories").select(
                "id,estado,image_url,image_original_url"
            ).eq("id", reservation_id).maybe_single().execute()
            persisted = result.data if result else None
        except Exception:
            logger.exception(
                "No se pudo reconciliar la reserva %s tras fallar la finalización; "
                "se conservan assets y reserva para revisión manual",
                reservation_id,
            )
            raise

        if persisted and persisted.get("estado") == "pendiente" \
                and persisted.get("image_url") == imagen_editada.url \
                and persisted.get("image_original_url") == uploaded.url:
            return persisted

        if persisted and persisted.get("estado") == "generando":
            try:
                uploads.delete_image(uploaded.public_id)
            except Exception:
                logger.exception("No se pudo borrar el original huérfano %s", uploaded.public_id)
            try:
                uploads.delete_image(imagen_editada.public_id)
            except Exception:
                logger.exception("No se pudo borrar el compuesto huérfano %s", imagen_editada.public_id)
            release_reservation()
        else:
            logger.error(
                "Estado indeterminado al finalizar la reserva %s: %r; "
                "se conservan assets y reserva para revisión manual",
                reservation_id,
                persisted,
            )
        raise

    return story

class StoryApproval(BaseModel):
    aprobado: bool


@router.patch("/historias/{story_id}/aprobar")
def approve_story(story_id: str, body: StoryApproval, employee: EmployeeDep):
    """Manually-uploaded stories start unapproved (see create_manual_story) and
    publish_daily() skips anything not approved — this is a real gate on
    publishing, not just a visual checkmark."""
    db = get_admin_client()
    result = db.table("stories").select("id,client_id,estado").eq("id", story_id).maybe_single().execute()
    story = result.data if result else None
    if not story:
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    _client_or_error(db, story["client_id"], employee.agency_id)
    if story.get("estado") in _LOCKED_STATES:
        raise HTTPException(status_code=409, detail="La historia ya fue publicada o cancelada")
    updated = db.table("stories").update({"aprobado": body.aprobado}).eq("id", story_id).execute().data
    return updated[0]


class DayTimePatch(BaseModel):
    hora_publicacion: str

    @field_validator("hora_publicacion")
    @classmethod
    def _valid_time(cls, value: str) -> str:
        if not _valid_hhmm(value):
            raise ValueError("Hora inválida (formato HH:MM)")
        return value


@router.patch("/clientes/{client_id}/dias/{fecha_publicacion}/hora")
def update_day_time(client_id: str, fecha_publicacion: str, body: DayTimePatch, employee: EmployeeDep):
    """Update every editable story on one date without changing client rhythm."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    stories = db.table("stories").select("id,estado,agendado,story_group_id").eq(
        "client_id", client_id
    ).eq("fecha_publicacion", fecha_publicacion).execute().data or []
    if not stories:
        raise HTTPException(status_code=404, detail="No hay historias para esa fecha")

    editable = [
        row for row in stories
        if not row.get("agendado") and row.get("estado") not in _LOCKED_STATES
    ]
    if not editable:
        raise HTTPException(status_code=409, detail="Las historias de esa fecha ya no se pueden editar")

    value = f"{body.hora_publicacion}:00"
    editable_ids = [row["id"] for row in editable]
    db.table("stories").update({"hora_publicacion": value}).in_(
        "id", editable_ids
    ).execute()
    editable_id_set = set(editable_ids)
    summary_group_ids = list({
        row["story_group_id"] for row in editable
        if all(
            other["id"] in editable_id_set
            for other in stories
            if other["story_group_id"] == row["story_group_id"]
        )
    })
    # scheduled_time summarizes the first date of a group. Update it only
    # after the publication rows succeed, and never rewrite the summary of a
    # group that already has a confirmed story on this date.
    if summary_group_ids:
        db.table("story_groups").update({"scheduled_time": value}).in_(
            "id", summary_group_ids
        ).eq("scheduled_date", fecha_publicacion).execute()
    return {"detail": "Hora actualizada", "updated": len(editable_ids)}


@router.patch("/clientes/{client_id}/historias/manual/{fecha_publicacion}/hora")
def update_manual_day_time(client_id: str, fecha_publicacion: str, body: DayTimePatch, employee: EmployeeDep):
    """Updates the shared publish time for every still-editable manual story on
    that date (the manual-upload group only — never touches an AI batch)."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    group = db.table("story_groups").select("id").eq("client_id", client_id).eq(
        "scheduled_date", fecha_publicacion
    ).is_("generation_week", "null").eq("agendado", False).execute().data
    if not group:
        raise HTTPException(status_code=404, detail="No hay historias manuales para esa fecha")
    stories = db.table("stories").select("id,estado,agendado").eq(
        "story_group_id", group[0]["id"]
    ).execute().data or []
    editable_ids = [
        row["id"] for row in stories
        if not row.get("agendado") and row.get("estado") not in _LOCKED_STATES
    ]
    if not editable_ids:
        raise HTTPException(status_code=409, detail="Las historias de esa fecha ya no se pueden editar")
    value = f"{body.hora_publicacion}:00"
    db.table("stories").update({"hora_publicacion": value}).in_("id", editable_ids).execute()
    # The group field is only a summary; update it after the publication rows.
    db.table("story_groups").update({"scheduled_time": value}).eq("id", group[0]["id"]).execute()
    return {"detail": "Hora actualizada", "updated": len(editable_ids)}


class DayDescriptionPatch(BaseModel):
    descripcion: str | None = Field(default=None, max_length=200)


@router.patch("/clientes/{client_id}/historias/manual/{fecha_publicacion}/descripcion")
def update_manual_day_description(client_id: str, fecha_publicacion: str, body: DayDescriptionPatch, employee: EmployeeDep):
    """Internal-only note on what a manual day's thread is about — never sent
    to Meta, never shown to the client. Shown as the title in the compact
    "Plan de la próxima semana" preview once the day is agendado."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    group = db.table("story_groups").select("id").eq("client_id", client_id).eq(
        "scheduled_date", fecha_publicacion
    ).is_("generation_week", "null").eq("agendado", False).execute().data
    if not group:
        raise HTTPException(status_code=404, detail="No hay historias manuales para esa fecha")
    updated = db.table("story_groups").update(
        {"descripcion": (body.descripcion or None)}
    ).eq("id", group[0]["id"]).execute().data
    return updated[0]


@router.patch("/clientes/{client_id}/dias/{fecha_publicacion}/agendar")
def schedule_day(client_id: str, fecha_publicacion: str, employee: EmployeeDep):
    """Confirms a whole day as scheduled — every story published that date is
    one publication regardless of source (AI batch, manual upload, or both),
    so this looks up by the stories' own fecha_publicacion (not
    story_groups.scheduled_date, which for an AI batch is its Monday batch
    start, not the individual day) and requires every one of them approved
    first. Once agendado, the day moves out of "Historias generadas" (the
    frontend's activeDates()) and shows as a small preview in "Plan de la
    próxima semana" instead — agendado never gates real publishing, that's
    still aprobado alone, so this can never change when something actually
    posts to Instagram."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    stories = db.table("stories").select("id,estado,aprobado,story_group_id").eq(
        "client_id", client_id
    ).eq("fecha_publicacion", fecha_publicacion).execute().data or []
    active = [row for row in stories if row.get("estado") not in _LOCKED_STATES]
    if not active:
        raise HTTPException(status_code=422, detail="No hay historias para agendar ese día")
    if not all(row.get("aprobado") for row in active):
        raise HTTPException(status_code=422, detail="Todavía hay historias sin aprobar ese día")
    story_ids = [row["id"] for row in active]
    db.table("stories").update({"agendado": True}).in_("id", story_ids).execute()

    # An AI group spans several publication dates.  Keep the legacy group flag
    # as a summary only: it becomes true after every active story in that group
    # has been scheduled, never after confirming just one date.
    group_ids = {row["story_group_id"] for row in active}
    for group_id in group_ids:
        group_stories = db.table("stories").select("id,estado,agendado").eq(
            "story_group_id", group_id
        ).execute().data or []
        relevant = [row for row in group_stories if row.get("estado") not in _LOCKED_STATES]
        if relevant and all(row.get("agendado") for row in relevant):
            db.table("story_groups").update({"agendado": True}).eq("id", group_id).execute()
    return {"detail": "Publicación agendada"}


@router.post("/clientes/{client_id}/dias/{fecha_publicacion}/publicar-ahora")
def publish_day_now(client_id: str, fecha_publicacion: str, employee: EmployeeDep):
    """Publish every approved pending story for one client and date immediately."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    stories = db.table("stories").select("id,estado,aprobado").eq(
        "client_id", client_id
    ).eq("fecha_publicacion", fecha_publicacion).execute().data or []
    active = [row for row in stories if row.get("estado") not in _LOCKED_STATES]
    if not active:
        raise HTTPException(status_code=422, detail="No hay historias para publicar ese día")
    if not all(row.get("aprobado") for row in active):
        raise HTTPException(status_code=422, detail="Todavía hay historias sin aprobar ese día")
    result = content_jobs.publish_now(db, client_id, fecha_publicacion)
    return {"detail": "Publicación enviada a Instagram", **result}


@router.patch("/historias/reordenar")
def reorder_stories(body: ReorderRequest, employee: EmployeeDep):
    ids = [item.story_id for item in body.historias]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Cada historia debe aparecer una sola vez")
    db = get_admin_client()
    stories = db.table("stories").select("id,story_group_id,client_id").in_("id", ids).execute().data or []
    if len(stories) != len(ids):
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    if len({row["story_group_id"] for row in stories}) != 1 or len({row["client_id"] for row in stories}) != 1:
        raise HTTPException(status_code=422, detail="Las historias deben pertenecer al mismo grupo")
    _client_or_error(db, stories[0]["client_id"], employee.agency_id)
    if len({item.nuevo_order for item in body.historias}) != len(body.historias):
        raise HTTPException(status_code=422, detail="Cada posición debe ser única")
    try:
        db.rpc("reorder_stories", {"p_orders": [
            {"story_id": item.story_id, "new_order": item.nuevo_order}
            for item in body.historias
        ]}).execute()
    except APIError:
        # Most likely someone else cancelled/moved a story in this group
        # concurrently, so the client's view of "all active stories" is stale.
        raise HTTPException(
            status_code=409,
            detail="El grupo de historias cambió mientras reordenabas. Recargá y probá de nuevo.",
        )
    return {"detail": "Orden actualizado"}


@router.patch("/historias/{story_id}")
def patch_story(story_id: str, body: StoryPatch, employee: EmployeeDep):
    db = get_admin_client()
    result = db.table("stories").select(
        "id,client_id,order,text,image_url,image_original_url,estado,font_choice"
    ).eq("id", story_id).maybe_single().execute()
    # postgrest-py's maybe_single() returns None outright (not a response with
    # data=None) when zero rows match — never chain `.data` directly onto it.
    story = result.data if result else None
    if not story:
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    client = _client_or_error(db, story["client_id"], employee.agency_id)
    if story.get("estado") in _LOCKED_STATES:
        raise HTTPException(status_code=409, detail="La historia ya fue publicada o cancelada y no se puede editar")
    if not story.get("image_original_url"):
        raise HTTPException(status_code=422, detail="La historia no tiene imagen original")
    response = requests.get(story["image_original_url"], timeout=30)
    response.raise_for_status()
    imagen_editada = content.editar_historia(
        build_content_config(client), response.content, body.texto_nuevo, story["order"],
        font_choice=story.get("font_choice"),
    )
    updated = db.table("stories").update({
        "text": body.texto_nuevo, "image_url": imagen_editada.url,
    }).eq("id", story_id).execute().data
    return updated[0] if isinstance(updated, list) and updated else {
        **story, "text": body.texto_nuevo, "image_url": imagen_editada.url,
    }


@router.post("/historias/{story_id}/generar-texto")
def generate_story_text(story_id: str, employee: EmployeeDep):
    """For a manually-uploaded story with no caption yet: has Claude look at
    the actual image (unlike the weekly-thread prompt, where the image is
    just background inspiration) and write one line in the client's voice,
    then composes it onto the image the same way the manual text-edit flow
    does (editar_historia) — this is additive, not a replacement of that
    flow, so the employee can still edit the result by hand afterward."""
    db = get_admin_client()
    result = db.table("stories").select(
        "id,client_id,order,text,image_url,image_original_url,estado,font_choice"
    ).eq("id", story_id).maybe_single().execute()
    story = result.data if result else None
    if not story:
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    client = _client_or_error(db, story["client_id"], employee.agency_id)
    if story.get("estado") in _LOCKED_STATES:
        raise HTTPException(status_code=409, detail="La historia ya fue publicada o cancelada y no se puede editar")
    if not story.get("image_original_url"):
        raise HTTPException(status_code=422, detail="La historia no tiene imagen original")
    response = requests.get(story["image_original_url"], timeout=30)
    response.raise_for_status()
    config = build_content_config(client)
    try:
        texto_nuevo = content.generar_texto_para_imagen(config, response.content)
    except ClaudeGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    imagen_editada = content.editar_historia(
        config, response.content, texto_nuevo, story["order"], font_choice=story.get("font_choice"),
    )
    updated = db.table("stories").update({
        "text": texto_nuevo, "image_url": imagen_editada.url,
    }).eq("id", story_id).execute().data
    return updated[0] if isinstance(updated, list) and updated else {
        **story, "text": texto_nuevo, "image_url": imagen_editada.url,
    }


class StoryFontPatch(BaseModel):
    font_choice: str | None = None

    @field_validator("font_choice")
    @classmethod
    def known_font(cls, value):
        if value is not None and value not in FONT_CHOICES:
            raise ValueError("Tipografía no reconocida")
        return value


@router.patch("/historias/{story_id}/tipografia")
def patch_story_font(story_id: str, body: StoryFontPatch, employee: EmployeeDep):
    """Overrides, for just this one Story, which bundled font the AI
    composes onto its image — null falls back to the client's own
    font_choice. Recomposes the existing image+text right away so the
    employee sees the result without a separate "regenerate" step."""
    db = get_admin_client()
    result = db.table("stories").select(
        "id,client_id,order,text,image_url,image_original_url,estado"
    ).eq("id", story_id).maybe_single().execute()
    story = result.data if result else None
    if not story:
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    client = _client_or_error(db, story["client_id"], employee.agency_id)
    if story.get("estado") in _LOCKED_STATES:
        raise HTTPException(status_code=409, detail="La historia ya fue publicada o cancelada y no se puede editar")
    if not story.get("image_original_url"):
        raise HTTPException(status_code=422, detail="La historia no tiene imagen original")
    if not story.get("text"):
        raise HTTPException(status_code=422, detail="La historia todavía no tiene texto para componer")
    response = requests.get(story["image_original_url"], timeout=30)
    response.raise_for_status()
    imagen_editada = content.editar_historia(
        build_content_config(client), response.content, story["text"], story["order"],
        font_choice=body.font_choice,
    )
    updated = db.table("stories").update({
        "font_choice": body.font_choice, "image_url": imagen_editada.url,
    }).eq("id", story_id).execute().data
    return updated[0] if isinstance(updated, list) and updated else {
        **story, "font_choice": body.font_choice, "image_url": imagen_editada.url,
    }


@router.delete("/historias/{story_id}")
def cancel_story(story_id: str, employee: EmployeeDep):
    db = get_admin_client()
    result = db.table("stories").select("id,client_id,estado").eq(
        "id", story_id
    ).maybe_single().execute()
    story = result.data if result else None
    if not story:
        raise HTTPException(status_code=404, detail="Historia no encontrada")
    _client_or_error(db, story["client_id"], employee.agency_id)
    if story.get("estado") in _LOCKED_STATES:
        raise HTTPException(status_code=409, detail="La historia ya fue publicada o cancelada")
    db.table("stories").update({"estado": "cancelada"}).eq("id", story_id).execute()
    return {"detail": "Historia cancelada"}
