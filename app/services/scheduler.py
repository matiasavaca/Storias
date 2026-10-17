"""
Tareas de Celery — publicación programada en Instagram.
"""
from __future__ import annotations
from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

TIMEZONE = "America/Argentina/Buenos_Aires"

def _make_celery(settings=None) -> Celery:
    _s = settings or get_settings()
    app = Celery("storias", broker=_s.redis_url, backend=_s.redis_url)
    app.conf.timezone = TIMEZONE
    app.conf.beat_schedule = {
        "generate-weekly-threads": {
            "task": "app.services.scheduler.generar_hilos_semanales",
            "schedule": crontab(minute=0, hour=18, day_of_week="fri"),
        },
        "publish-daily-stories": {
            # Every 1 min, not every 15: clients can set their own per-day
            # publish time (content_jobs.publish_schedule) down to the
            # minute, so this has to check as close to continuously as
            # practical to publish close to that exact minute instead of
            # waiting for the next 15-min tick (previously up to ~14 min late).
            "task": "app.services.scheduler.publicar_historias_pendientes",
            "schedule": crontab(minute="*"),
        },
    }
    return app

celery_app = _make_celery()


@celery_app.task(name="app.services.scheduler.generar_hilos_semanales")
def generar_hilos_semanales() -> None:
    """Enqueue one generation task per active client for worker concurrency."""
    from app.db.supabase import get_admin_client
    db = get_admin_client()
    client_ids = [row["id"] for row in db.table("clients").select("id").eq(
        "active", True
    ).execute().data or []]
    for client_id in client_ids:
        generar_hilo_cliente.delay(client_id)


@celery_app.task(name="app.services.scheduler.generar_hilo_cliente")
def generar_hilo_cliente(client_id: str) -> None:
    from app.db.supabase import get_admin_client
    from app.services.content_jobs import generate_for_client_by_id
    generate_for_client_by_id(get_admin_client(), client_id)


@celery_app.task(name="app.services.scheduler.publicar_historias_pendientes")
def publicar_historias_pendientes() -> None:
    from app.db.supabase import get_admin_client
    from app.services.content_jobs import publish_daily
    publish_daily(get_admin_client())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def schedule_publication(self, story_group_id: str) -> None:
    """
    Publica las historias aprobadas en Instagram vía Meta Graph API.
    Se reintenta hasta 3 veces si falla (red, rate limit, etc.)
    """
    from app.db.supabase import get_admin_client
    from app.services.encryption import decrypt
    import httpx, datetime

    db = get_admin_client()
    access_token = None

    try:
        group = db.table("story_groups").select(
            "*, clients(meta_access_token_encrypted, instagram_account_id)"
        ).eq("id", story_group_id).single().execute()

        stories = db.table("stories").select("*").eq(
            "story_group_id", story_group_id
        ).eq("approved_at", "not.is.null").order("order").execute()

        client_data = group.data["clients"]
        access_token = decrypt(client_data["meta_access_token_encrypted"])
        ig_account = client_data["instagram_account_id"]

        for story in stories.data:
            with httpx.Client() as http:
                # 1. Crear media container
                container = http.post(
                    f"https://graph.facebook.com/v21.0/{ig_account}/media",
                    params={
                        "image_url": story["image_url"],
                        "caption": story["text"],
                        "media_type": "STORIES",
                        "access_token": access_token,
                    },
                    timeout=15,
                )
                container.raise_for_status()
                container_id = container.json()["id"]

                # 2. Publicar
                http.post(
                    f"https://graph.facebook.com/v21.0/{ig_account}/media_publish",
                    params={"creation_id": container_id, "access_token": access_token},
                    timeout=15,
                ).raise_for_status()

        db.table("story_groups").update({
            "status": "published",
            "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", story_group_id).execute()

    except Exception as exc:
        # httpx embeds the full request URL (including access_token, since it's
        # sent as a query param) in HTTPStatusError messages. Never let a live
        # Meta token reach Celery's result backend/logs via a retried exception.
        message = str(exc)
        if access_token:
            message = message.replace(access_token, "[redacted]")
        self.retry(exc=RuntimeError(message))
