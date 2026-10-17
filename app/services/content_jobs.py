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
        font_choice=row.get("font_choice"),
    )


def _valid_hhmm(value) -> bool:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    hour, _, minute = value.partition(":")
    return hour.isdigit() and minute.isdigit() and 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59


def publish_schedule(row: dict) -> tuple[tuple[int, str, int], ...]:
    """Return the client's per-day schedule and story counts.

    Rows saved before explicit counts existed preserve their old even split,
    including the legacy ``publish_together`` behavior. Malformed schedules
    fall back to the four global publication days with one story per day.
    """
    days = row.get("publish_days")
    parsed = None
    if isinstance(days, list) and 1 <= len(days) <= 4:
        try:
            entries = [(int(entry["day"]), str(entry["time"]), entry.get("count"))
                       for entry in days]
        except (KeyError, TypeError, ValueError):
            entries = None
        if entries is not None:
            weekdays = {day for day, _, _ in entries}
            if len(weekdays) == len(entries) and all(0 <= day <= 6 for day in weekdays) \
                    and all(_valid_hhmm(hhmm) for _, hhmm, _ in entries):
                parsed = sorted(entries, key=lambda entry: entry[0])
    if parsed is None:
        settings = get_settings()
        default_time = f"{settings.publication_hour:02d}:{settings.publication_minute:02d}"
        return tuple((offset, default_time, 1) for offset in PUBLISH_DAY_OFFSETS)

    counts = [count for _, _, count in parsed]
    if all(isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 4
           for count in counts) and sum(counts) == 4:
        return tuple((day, time, count) for day, time, count in parsed)

    n = len(parsed)
    if row.get("publish_together"):
        legacy_counts = [4] + [0] * (n - 1)
    else:
        legacy_counts = [0] * n
        for i in range(4):
            legacy_counts[(i * n) // 4] += 1
    return tuple((day, time, count)
                 for (day, time, _), count in zip(parsed, legacy_counts))


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
    schedule = publish_schedule(row)
    story_schedule = [(day, time) for day, time, count in schedule for _ in range(count)]
    publish_dates = [next_monday + timedelta(days=offset) for offset, _ in story_schedule]
    return {
        "p_client_id": config.client_id,
        "p_generation_week": monday.isoformat(),
        "p_scheduled_date": next_monday.isoformat(),
        "p_scheduled_time": f"{schedule[0][1]}:00",
        "p_used_focus": config.weekly_focus,
        "p_used_focus_expires_at": row.get("weekly_focus_expires_at"),
        "p_stories": [{"text": result.historias[i], "image_url": result.imagenes_editadas_url[i],
            "image_original_url": result.imagenes_originales_url[i],
            "fecha_publicacion": publish_dates[i].isoformat(),
            "hora_publicacion": f"{story_schedule[i][1]}:00",
            # Read what the engine actually drew on the image (result.cta_agregado),
            # don't re-roll the dice here: a second independent draw could disagree
            # with the composed image and persist a flag that doesn't match it.
            "agregar_cta": i == 3 and result.cta_agregado} for i in range(4)],
        "p_images": [{"drive_file_id": id, "drive_file_name": names[id]}
                     for id in result.drive_file_ids_usados],
    }


def seleccionar_imagenes(disponibles: list[tuple], historial: list[dict],
                         ahora: datetime, semanas_cooldown: int = NO_REPEAT_WEEKS,
                         limite: int | None = 4) -> tuple[list[tuple], bool]:
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
    ranked = chosen + [image for _, image in sorted(recent, key=lambda item: item[0])]
    selected = ranked if limite is None else ranked[:limite]
    return selected, len(selected) < 4 or len(chosen) < 4


def generate_for_client(db, row: dict, today: date) -> dict:
    """Generate and persist the upcoming weekly thread for one client.

    ``created=False`` is an idempotent no-op: content for this generation
    week already exists and still has at least one live story. If every
    story from that week's batch was cancelled, the old group is deleted
    (cascading to its stories) and a fresh one is generated instead — a
    fully-cancelled week should be regenerable, not stuck until next Monday.
    A group with zero stories (shouldn't happen in practice — generation
    always creates exactly 4 together) is treated conservatively as still
    blocking, not as regenerable. All operational failures propagate so each
    caller can decide whether to persist, display, or otherwise handle them.
    """
    week = (today - timedelta(days=today.weekday())).isoformat()
    existing = db.table("story_groups").select("id").eq(
        "client_id", row["id"]
    ).eq("generation_week", week).execute().data
    if existing:
        group_id = existing[0]["id"]
        stories = db.table("stories").select("estado").eq(
            "story_group_id", group_id
        ).execute().data or []
        if not stories or any(story.get("estado") != "cancelada" for story in stories):
            return {"created": False, "group_id": group_id, "recycled": False}
        db.table("story_groups").delete().eq("id", group_id).execute()

    config = build_content_config(row)
    available = drive.list_image_metadata(row.get("drive_folder_id"))
    if len(available) < 4:
        raise ValueError(f"sin imágenes suficientes: {len(available)} disponibles; se requieren 4")
    try:
        history = _all_rows(db.table("client_images").select(
            "drive_file_id,last_used_at"
        ).eq("client_id", row["id"]))
    except Exception as exc:
        logger.exception("Could not read image history for client %s", row["id"])
        raise RuntimeError("No se pudo leer el historial de imágenes usadas") from exc
    now = datetime.now(timezone.utc)
    ranked, _ = seleccionar_imagenes(available, history, now, limite=None)
    selected_rows = drive.download_images(ranked, limit=4)
    if len(selected_rows) < 4:
        raise ValueError(
            f"sin imágenes legibles suficientes: {len(selected_rows)} disponibles; se requieren 4"
        )
    _, recycled = seleccionar_imagenes(selected_rows, history, now)
    selected = [ImagenCandidata(drive_file_id=id, drive_file_name=name, image_bytes=data)
                for id, name, data in selected_rows]
    result = content.generar_hilo(config, selected)
    persisted = db.rpc(
        "persist_generated_thread", _thread_payload(row, config, result, selected, today)
    ).execute()
    if recycled:
        # This is a benign, informational event, not a failure: don't write
        # it into generation_error, whose documented contract (AGENTS.md)
        # is "the last generation error" and gets cleared on every success.
        logger.warning("Client %s generated with image recycling (pool_bajo)", row["id"])
    try:
        # Bookkeeping is intentionally separate from the generation RPC: a
        # successful thread must stay successful if this informational update
        # happens to fail after the transaction has committed.
        db.table("clients").update({
            "pool_bajo_at": now.isoformat() if recycled else None
        }).eq("id", row["id"]).execute()
    except Exception:
        logger.exception("Could not persist pool_bajo_at for client %s", row["id"])
    group_id = str(persisted.data) if persisted.data is not None else None
    return {"created": True, "group_id": group_id, "recycled": recycled}


def _generate_for_client_safe(db, row: dict, today: date) -> None:
    """Isolate one client's failure without stopping the remaining clients."""
    try:
        generate_for_client(db, row, today)
    except Exception as exc:
        logger.error("Weekly generation failed for client %s: %s", row["id"], type(exc).__name__)
        try:
            db.table("clients").update({"generation_error": str(exc),
                "generation_error_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
        except Exception:
            logger.error("Could not persist generation error for client %s", row["id"])


def generate_weekly(db, today: date | None = None) -> None:
    """Generate every active client synchronously for manual use and tests.

    The Friday Celery task instead fans out one task per client, letting the
    worker process multiple generations concurrently.
    """
    today = today or local_today()
    clients = _all_rows(db.table("clients").select("*").eq("active", True).order("id"))
    for row in clients:
        _generate_for_client_safe(db, row, today)


def generate_for_client_by_id(db, client_id: str, today: date | None = None) -> None:
    """Generate one active client from a row fetched when this task executes."""
    today = today or local_today()
    rows = db.table("clients").select("*").eq("id", client_id).eq("active", True).execute().data or []
    if not rows:
        logger.warning(
            "Client %s is no longer active or was not found; skipping fanned-out generation",
            client_id,
        )
        return
    _generate_for_client_safe(db, rows[0], today)


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


def _claim_and_publish(db, stories: list[dict]) -> dict:
    """Claim stories before publishing so concurrent callers cannot double-post."""
    published = failed = 0
    for story in stories:
        try:
            claimed = db.table("stories").update({"estado": "publicando"}).eq(
                "id", story["id"]).eq("estado", story["estado"]).execute().data
            if not claimed:
                continue
            outcome = _publish_story(story)
            db.table("stories").update(outcome).eq("id", story["id"]).eq(
                "estado", "publicando").execute()
            if outcome["estado"] == "publicado":
                published += 1
            else:
                failed += 1
        except Exception:
            # A write failure after Meta may mean it was published: leave the claim
            # for manual reconciliation, never blindly retry the external side effect.
            logger.error("Publication needs reconciliation for story %s", story["id"])
            failed += 1
    return {"publicadas": published, "fallidas": failed}


def publish_daily(db, today: date | None = None, now: datetime | None = None) -> None:
    """Runs frequently (every 15 min, see scheduler.py) rather than once a day,
    so each story publishes close to its own hora_publicacion instead of all of
    today's stories firing together at one fixed daily time."""
    today = today or local_today()
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    query = db.table("stories").select(
        "*, clients(instagram_account_id, meta_access_token_encrypted, calendly_link)"
    ).eq("fecha_publicacion", today.isoformat()).eq("estado", "pendiente").eq("aprobado", True)
    # hora_publicacion is nullable (rows from before this column existed): treat
    # those as always due, same as the old once-a-day behavior.
    query = query.or_(f"hora_publicacion.is.null,hora_publicacion.lte.{now.strftime('%H:%M:%S')}")
    stories = _all_rows(query.order("story_group_id").order("order").order("id"))
    _claim_and_publish(db, stories)


def publish_now(db, client_id: str, fecha_publicacion: str) -> dict:
    """Publish one client's approved pending or failed stories immediately."""
    query = db.table("stories").select(
        "*, clients(instagram_account_id, meta_access_token_encrypted, calendly_link)"
    ).eq("client_id", client_id).eq("fecha_publicacion", fecha_publicacion).in_(
        "estado", ["pendiente", "error"]
    ).eq("aprobado", True)
    stories = _all_rows(query.order("story_group_id").order("order").order("id"))
    return _claim_and_publish(db, stories)
