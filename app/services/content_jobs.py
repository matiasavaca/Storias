"""Portal orchestration: engine calls, transactional persistence and publication."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engine import content
from app.engine.schemas import ClientContentConfig, HiloGenerado, ImagenCandidata
from app.services import drive
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)
TIMEZONE = "America/Argentina/Buenos_Aires"
# Global cooldown for image reuse. This may become a per-client setting later.
NO_REPEAT_WEEKS = 3
# Days after the target week's Monday each of the 4 weekly stories publishes
# on: Mon/Wed/Fri/Sun, spreading the thread across the week instead of
# dumping all 4 the same day.
PUBLISH_DAY_OFFSETS = (0, 2, 4, 6)


def local_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def build_content_config(row: dict) -> ClientContentConfig:
    """Build the engine's config from a raw `clients` row, defaulting the
    fields the DB allows to be NULL but the engine requires to be set."""
    return ClientContentConfig(
        client_id=row["id"], nombre_negocio=row["name"],
        business_description=row.get("business_description") or "",
        weekly_focus=row.get("weekly_focus"), tone_examples=row.get("tone_examples") or [],
        topics=row.get("topics"), logo_url=row.get("logo_url"),
        calendly_link=row.get("calendly_link"), prob_link=row.get("prob_link") or 0.0,
    )


def publish_day_offsets(row: dict) -> tuple[int, ...]:
    """A client's custom publishing cadence (4 unique weekday offsets, 0=Mon..6=Sun),
    or the global default if unset/invalid."""
    days = row.get("publish_days")
    if isinstance(days, list) and len(set(days)) == 4 and all(isinstance(d, int) and 0 <= d <= 6 for d in days):
        return tuple(sorted(days))
    return PUBLISH_DAY_OFFSETS


def _all_rows(query):
    """Collect the snapshot before updates alter a pending query's offsets."""
    rows, offset = [], 0
    while True:
        page = query.range(offset, offset + 499).execute().data
        rows.extend(page)
        if len(page) < 500:
            return rows
        offset += 500


def _thread_payload(row: dict, config: ClientContentConfig, result: HiloGenerado,
                    images: list[ImagenCandidata], today: date) -> dict:
    if any(len(items) != 4 for items in (result.historias, result.imagenes_originales_url,
            result.imagenes_editadas_url, result.drive_file_ids_usados)):
        raise ValueError("Engine must return exactly four complete stories and images")
    names = {image.drive_file_id: image.drive_file_name for image in images}
    if len(set(result.drive_file_ids_usados)) != 4 or set(result.drive_file_ids_usados) != set(names):
        raise ValueError("Engine returned unexpected Drive image IDs")
    monday = today - timedelta(days=today.weekday())
    next_monday = monday + timedelta(days=7)
    publish_dates = [next_monday + timedelta(days=offset) for offset in publish_day_offsets(row)]
    settings = get_settings()
    return {
        "p_client_id": config.client_id,
        "p_generation_week": monday.isoformat(),
        "p_scheduled_date": next_monday.isoformat(),
        "p_scheduled_time": f"{settings.publication_hour:02d}:{settings.publication_minute:02d}:00",
        "p_used_focus": config.weekly_focus,
        "p_used_focus_expires_at": row.get("weekly_focus_expires_at"),
        "p_stories": [{"text": result.historias[i], "image_url": result.imagenes_editadas_url[i],
            "image_original_url": result.imagenes_originales_url[i],
            "fecha_publicacion": publish_dates[i].isoformat(),
            # Read what the engine actually drew on the image (result.cta_agregado),
            # don't re-roll the dice here: a second independent draw could disagree
            # with the composed image and persist a flag that doesn't match it.
            "agregar_cta": i == 3 and result.cta_agregado} for i in range(4)],
        "p_images": [{"drive_file_id": id, "drive_file_name": names[id]}
                     for id in result.drive_file_ids_usados],
    }


def seleccionar_imagenes(disponibles: list[tuple[str, str, bytes]], historial: list[dict],
                         ahora: datetime, semanas_cooldown: int = NO_REPEAT_WEEKS
                         ) -> tuple[list[tuple[str, str, bytes]], bool]:
    """Select four images, preferring never-used and cooldown-expired files."""
    cutoff = ahora - timedelta(weeks=semanas_cooldown)
    history = {row["drive_file_id"]: row.get("last_used_at") for row in historial}

    def parsed(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    never, expired, recent = [], [], []
    for image in disponibles:
        used_at = parsed(history.get(image[0])) if image[0] in history else None
        if image[0] not in history:
            never.append(image)
        elif used_at is None or used_at <= cutoff:
            expired.append((used_at or datetime.min.replace(tzinfo=timezone.utc), image))
        else:
            recent.append((used_at, image))

    chosen = never + [image for _, image in sorted(expired, key=lambda item: item[0])]
    if len(chosen) >= 4:
        return chosen[:4], False
    recycled = chosen + [image for _, image in sorted(recent, key=lambda item: item[0])]
    return recycled[:4], len(recycled) < 4 or len(chosen) < 4


def generate_weekly(db, today: date | None = None) -> None:
    today = today or local_today()
    week = (today - timedelta(days=today.weekday())).isoformat()
    clients = _all_rows(db.table("clients").select("*").eq("active", True).order("id"))
    for row in clients:
        try:
            existing = db.table("story_groups").select("id").eq(
                "client_id", row["id"]).eq("generation_week", week).execute().data
            if existing:
                continue
            config = build_content_config(row)
            available = drive.list_images(row.get("drive_folder_id"))
            if len(available) < 4:
                raise ValueError(f"sin imágenes suficientes: {len(available)} disponibles; se requieren 4")
            try:
                history = _all_rows(db.table("client_images").select(
                    "drive_file_id,last_used_at"
                ).eq("client_id", row["id"]))
            except Exception:
                history = []
            selected_rows, recycled = seleccionar_imagenes(available, history,
                datetime.now(timezone.utc))
            selected = [ImagenCandidata(drive_file_id=id, drive_file_name=name, image_bytes=data)
                        for id, name, data in selected_rows]
            result = content.generar_hilo(config, selected)
            db.rpc("persist_generated_thread", _thread_payload(row, config, result, selected, today)).execute()
            if recycled:
                # This is a benign, informational event, not a failure: don't write
                # it into generation_error, whose documented contract (AGENTS.md)
                # is "the last generation error" and gets cleared on every success.
                # TODO(B3): give this its own column and expose it in the health dashboard.
                logger.warning("Client %s generated with image recycling (pool_bajo)", row["id"])
        except Exception as exc:
            logger.error("Weekly generation failed for client %s: %s", row["id"], type(exc).__name__)
            try:
                db.table("clients").update({"generation_error": str(exc),
                    "generation_error_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
            except Exception:
                logger.error("Could not persist generation error for client %s", row["id"])


def _publish_story(story: dict) -> dict:
    token = None
    client = story.get("clients") or {}
    try:
        token = decrypt(client["meta_access_token_encrypted"])
        result = content.publicar_historia(image_url=story["image_url"],
            instagram_account_id=client["instagram_account_id"], meta_access_token=token,
            agregar_cta=story["agregar_cta"], calendly_link=client.get("calendly_link"))
        if result.ok:
            return {"estado": "publicado", "ig_media_id": result.ig_media_id, "error": None,
                    "published_at": datetime.now(timezone.utc).isoformat()}
        message = result.error or "Meta publication failed"
    except Exception as exc:
        message = str(exc)
    # Some HTTP errors include request URLs. Never persist access tokens from them.
    for secret in (token, client.get("meta_access_token_encrypted")):
        if secret:
            message = message.replace(secret, "[redacted]")
    return {"estado": "error", "error": message}


def publish_daily(db, today: date | None = None) -> None:
    today = today or local_today()
    stories = _all_rows(db.table("stories").select(
        "*, clients(instagram_account_id, meta_access_token_encrypted, calendly_link)"
    ).eq("fecha_publicacion", today.isoformat()).eq("estado", "pendiente")
      .order("story_group_id").order("order").order("id"))
    for story in stories:
        try:
            claimed = db.table("stories").update({"estado": "publicando"}).eq(
                "id", story["id"]).eq("estado", "pendiente").execute().data
            if not claimed:
                continue
            outcome = _publish_story(story)
            db.table("stories").update(outcome).eq("id", story["id"]).eq(
                "estado", "publicando").execute()
        except Exception:
            # A write failure after Meta may mean it was published: leave the claim
            # for manual reconciliation, never blindly retry the external side effect.
            logger.error("Publication needs reconciliation for story %s", story["id"])
