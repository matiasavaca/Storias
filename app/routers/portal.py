"""Authenticated API used by the employee portal."""
from __future__ import annotations

from datetime import date

import requests
from fastapi import APIRouter, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.db.supabase import get_admin_client
from app.deps import EmployeeDep
from app.engine import content
from app.engine.schemas import ImagenCandidata
from app.services import drive
from app.services.content_jobs import PUBLISH_DAY_OFFSETS, build_content_config

router = APIRouter(prefix="/portal", tags=["portal"])

# Stories in these states already happened (or are mid-flight) on Instagram:
# editing or cancelling them would silently diverge the DB from what's live.
_LOCKED_STATES = {"publicando", "publicado", "cancelada"}

_CLIENT_DETAIL = (
    "id,agency_id,name,business_description,weekly_focus,"
    "weekly_focus_expires_at,tone_examples,topics,drive_folder_id,logo_url,"
    "calendly_link,prob_link,generation_error,generation_error_at,team_id,publish_days"
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


class ClientTeamPatch(BaseModel):
    team_id: str | None = None


class ScheduleEntry(BaseModel):
    day: int = Field(ge=0, le=6)
    time: str

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
    def exactly_four_distinct_weekdays(cls, value):
        if value is None:
            return None
        days = [entry.day for entry in value]
        if len(value) != 4 or len(set(days)) != 4:
            raise ValueError("publish_days debe tener exactamente 4 días distintos (0=lunes..6=domingo)")
        return sorted(value, key=lambda entry: entry.day)


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class StoryPatch(BaseModel):
    texto_nuevo: str = Field(min_length=1)


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
            "role": employee.role, "agency_id": employee.agency_id, "team_id": employee.team_id}


@router.get("/equipos")
def list_teams(employee: EmployeeDep):
    db = get_admin_client()
    return db.table("teams").select("id,name").eq(
        "agency_id", employee.agency_id
    ).order("name").execute().data or []


@router.post("/equipos")
def create_team(body: TeamCreate, employee: EmployeeDep):
    db = get_admin_client()
    name = body.name.strip()
    try:
        created = db.table("teams").insert(
            {"agency_id": employee.agency_id, "name": name}
        ).execute().data
    except APIError:
        raise HTTPException(status_code=409, detail="Ya existe un equipo con ese nombre")
    return created[0] if isinstance(created, list) and created else {"name": name}


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
        rows = db.table("stories").select("client_id").in_("client_id", ids).neq(
            "estado", "cancelada"
        ).gte("fecha_publicacion", date.today().isoformat()).execute().data or []
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["client_id"]] = counts.get(row["client_id"], 0) + 1
        for c in clients:
            c["stories_count"] = counts.get(c["id"], 0)
    return clients


@router.get("/clientes/{client_id}")
def get_client(client_id: str, employee: EmployeeDep):
    return _client_or_error(get_admin_client(), client_id, employee.agency_id)


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


@router.patch("/clientes/{client_id}/equipo")
def patch_client_team(client_id: str, body: ClientTeamPatch, employee: EmployeeDep):
    """Reassign which team manages this client — purely organizational, so it
    goes through a plain update instead of the audited update_client_prompt RPC."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    if body.team_id is not None:
        team = db.table("teams").select("id").eq("id", body.team_id).eq(
            "agency_id", employee.agency_id
        ).maybe_single().execute()
        if not team or not team.data:
            raise HTTPException(status_code=422, detail="Equipo no encontrado en tu agencia")
    updated = db.table("clients").update({"team_id": body.team_id}).eq(
        "id", client_id
    ).execute().data
    return updated[0] if isinstance(updated, list) and updated else {"id": client_id, "team_id": body.team_id}


@router.patch("/clientes/{client_id}/ritmo")
def patch_client_ritmo(client_id: str, body: ClientRitmoPatch, employee: EmployeeDep):
    """Which 4 weekdays (and what time each one) this client's weekly thread
    publishes on — purely a scheduling setting, so a plain update instead of
    the audited RPC."""
    db = get_admin_client()
    _client_or_error(db, client_id, employee.agency_id)
    days = [entry.model_dump() for entry in body.publish_days] if body.publish_days else None
    updated = db.table("clients").update({"publish_days": days}).eq(
        "id", client_id
    ).execute().data
    return updated[0] if isinstance(updated, list) and updated else {"id": client_id, "publish_days": days}


@router.get("/ritmo-default")
def get_default_ritmo(employee: EmployeeDep):
    settings = get_settings()
    default_time = f"{settings.publication_hour:02d}:{settings.publication_minute:02d}"
    return {"publish_days": [{"day": day, "time": default_time} for day in PUBLISH_DAY_OFFSETS]}


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
            if story.get("estado") != "cancelada"
        ]
    return groups


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
        "id,client_id,order,text,image_url,image_original_url,estado"
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
    image_url = content.editar_historia(
        build_content_config(client), response.content, body.texto_nuevo, story["order"],
    )
    updated = db.table("stories").update({
        "text": body.texto_nuevo, "image_url": image_url,
    }).eq("id", story_id).execute().data
    return updated[0] if isinstance(updated, list) and updated else {
        **story, "text": body.texto_nuevo, "image_url": image_url,
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
