"""One-off real A2/A3 smoke test for a single isolated client."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from app.db.supabase import get_admin_client
from app.engine import content
from app.engine.schemas import ClientContentConfig, ImagenCandidata
from app.services import drive
from app.services.content_jobs import _thread_payload, seleccionar_imagenes


FOLDER_ID = "1cfAEixGG4xenMoykMcB_gfI7zqD3M9kr"
BUSINESS_DESCRIPTION_CUAN = (
    "Sos el copywriter de CUAN, un estudio que diseña cocinas "
    "a medida para personas que están construyendo o remodelando "
    "su casa. Tu público NO son arquitectos ni diseñadores: son "
    "personas comunes armando su casa, muchas veces por primera vez."
)
TONE_EXAMPLES_CUAN = [
    ["El error más caro de una cocina no es la mesada.", "Es construir algo que después no funciona.", "Por eso diseñamos todo en 3D antes de la obra.", "¿Pensás renovar tu cocina? Escribí COCINA."],
    ["¿Tu cocina se siente chica?", "Muchas veces no faltan metros.", "Falta una mejor distribución.", "Mandá DISEÑO y te mostramos posibilidades."],
    ["La mayoría elige materiales demasiado pronto.", "Y se olvida de lo más importante.", "La distribución.", "Escribí PLAN y te contamos cómo trabajamos."],
    ["¿Querés una isla?", "No siempre es la mejor solución.", "Cada cocina necesita una estrategia distinta.", "Mandá PROYECTO y lo vemos juntos."],
    ["Tu cocina te va a acompañar años.", "No diseñes a prueba y error.", "Visualizala completa antes de construir.", "Escribí COCINA para agendar una reunión."],
    ["Una decisión puede arruinar toda una cocina.", "Y la mayoría la toma demasiado rápido.", "Te contamos cuál es en la reunión.", "Mandá QUIERO y coordinamos."],
]
TOPICS_CUAN = [
    "distribucion del espacio en la cocina", "errores comunes al diseñar una cocina",
    "diseño 3D antes de la obra", "islas de cocina: cuando conviene y cuando no",
    "eleccion de materiales para cocina", "mesadas y superficies",
    "guardado y almacenamiento en la cocina", "errores caros al renovar la cocina",
    "planificar la cocina antes de construir", "decisiones que arruinan el diseño de una cocina",
]


def execute() -> dict:
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ANTHROPIC_API_KEY",
                "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
                "GOOGLE_SERVICE_ACCOUNT_FILE"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    db = get_admin_client()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    agency = db.table("agencies").insert({
        "name": f"A3 Real Smoke {suffix}", "slug": f"a3-real-smoke-{suffix.lower()}",
        "plan": "basic",
    }).execute().data[0]
    client_payload = {
        "agency_id": agency["id"], "name": f"CUAN A3 Real Smoke {suffix}",
        "contact_name": "Smoke Test", "contact_email": f"smoke-{suffix}@example.invalid",
        "business_description": BUSINESS_DESCRIPTION_CUAN, "tone_examples": TONE_EXAMPLES_CUAN,
        "topics": TOPICS_CUAN, "drive_folder_id": FOLDER_ID, "prob_link": 0.0,
        "active": True, "option": "opcion2",
    }
    client = db.table("clients").insert(client_payload).execute().data[0]
    report = {"agency_id": agency["id"], "client_id": client["id"], "client_name": client["name"]}
    try:
        available = drive.list_images(FOLDER_ID)
        report["drive_image_count"] = len(available)
        if len(available) < 4:
            raise RuntimeError(f"Drive folder contains only {len(available)} images; four required")
        history = db.table("client_images").select("drive_file_id,last_used_at").eq(
            "client_id", client["id"]).execute().data
        selected_rows, recycled = seleccionar_imagenes(available, history, datetime.now(timezone.utc))
        selected = [ImagenCandidata(drive_file_id=file_id, drive_file_name=name, image_bytes=data)
                    for file_id, name, data in selected_rows]
        report["selected_drive_file_ids"] = [image.drive_file_id for image in selected]
        report["selected_drive_file_names"] = [image.drive_file_name for image in selected]
        report["recycled"] = recycled
        config = ClientContentConfig(
            client_id=client["id"], nombre_negocio=client["name"],
            business_description=client["business_description"],
            tone_examples=client["tone_examples"], topics=client["topics"],
            weekly_focus=client.get("weekly_focus"), logo_url=client.get("logo_url"),
            calendly_link=client.get("calendly_link"), prob_link=client.get("prob_link") or 0.0,
        )
        result = content.generar_hilo(config, selected)
        report["story_count_from_claude"] = len(result.historias)
        report["stories"] = result.historias
        report["original_urls"] = result.imagenes_originales_url
        report["edited_urls"] = result.imagenes_editadas_url
        report["cloudinary_urls_valid"] = all(
            isinstance(url, str) and url.startswith("https://res.cloudinary.com/")
            for url in result.imagenes_originales_url + result.imagenes_editadas_url
        )
        rpc = db.rpc("persist_generated_thread", _thread_payload(
            client, config, result, selected, date.today())).execute()
        group_id = rpc.data
        report["story_group_id"] = group_id
        report["story_groups"] = db.table("story_groups").select("*").eq(
            "id", group_id).execute().data
        report["persisted_stories"] = db.table("stories").select(
            "id,story_group_id,client_id,order,text,image_url,image_original_url,fecha_publicacion,estado,agregar_cta"
        ).eq("story_group_id", group_id).order("order").execute().data
        report["client_images"] = db.table("client_images").select(
            "id,client_id,drive_file_id,drive_file_name,last_used_at,times_used"
        ).eq("client_id", client["id"]).order("drive_file_name").execute().data
        report["client_after"] = db.table("clients").select(
            "id,name,generation_error,generation_error_at"
        ).eq("id", client["id"]).single().execute().data
        report["error"] = None
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            db.table("clients").update({
                "generation_error": str(exc), "generation_error_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", client["id"]).execute()
        except Exception as persist_exc:
            report["error_persist_failure"] = f"{type(persist_exc).__name__}: {persist_exc}"
    return report


if __name__ == "__main__":
    outcome = execute()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    sys.exit(1 if outcome.get("error") else 0)
