# Contrato de integración — Motor de Contenido ↔ Portal Storias

Este documento es la referencia compartida entre las dos mitades del proyecto para que Claude (motor de contenido) y Codex (portal SaaS) puedan trabajar en paralelo sin pisarse ni divergir en supuestos. Cualquier cambio a una firma de función, tabla o campo de acá se actualiza en este documento ANTES de tocar el código de los dos lados.

**Cómo usarlo:** guardar este archivo como `AGENTS.md` en la raíz del repo (Codex CLI lo lee automático como instrucciones de repo) y una copia o symlink como `CLAUDE.md` (Claude Code hace lo mismo). Así ninguna de las dos IAs necesita que se lo pegues a mano en cada sesión.

---

## 1. Principio de división

Un solo repo, dos zonas con dueño y responsabilidad separados:

- **`app/engine/`** — dueño: Gonza + Claude. Funciones puras de generación y edición de contenido (prompt a Claude Vision, composición de imagen con Pillow, subida a Cloudinary, publicación en Meta). **Nunca toca Supabase ni Drive directamente para leer/escribir estado** — recibe todo lo que necesita como parámetro y devuelve datos. Es el mismo motor de `C:\Cuan\main.py`, generalizado para recibir el prompt/config por cliente en vez de tenerlo hardcodeado.
- **Todo lo demás** (`app/routers/`, `app/services/`, `app/models/`, `app/db/`, `templates/`, tareas de Celery) — dueño: Matías + Codex. Dueño de la base de datos, la cola de trabajo, la auth, el portal de empleados y de conectar Drive para armar el pool de imágenes disponibles. Es quien **llama** a las funciones de `app/engine` y persiste lo que devuelven.

Regla dura: ningún archivo se edita desde los dos lados a la vez. Si hace falta un cambio de contrato (agregar un campo, cambiar una firma), se actualiza este documento primero y se avisa al otro lado.

---

## 2. Tablas de Supabase que el engine necesita que existan (las crea/migra el lado Codex)

Extienden el `supabase_schema.sql` que ya armó Matías.

**`clients`** — agregar columnas:
| Campo | Tipo | Notas |
|---|---|---|
| `business_description` | text | Personaje/tono estable del cliente — reemplaza el bloque hardcodeado "Sos el copywriter de CUAN..." de `main.py` |
| `tone_examples` | jsonb | Array de hilos de ejemplo, cada uno como array de 4 strings — reemplaza los 6 ejemplos hardcodeados |
| `topics` | jsonb | Array de temas posibles (strings). Si es null/vacío, el engine no elige tema random — usa `weekly_focus` obligatorio o un tema genérico |
| `weekly_focus` | text, nullable | Instrucción puntual de esta semana (ej. "destacar la venta que cerramos el martes"). Si está cargado, reemplaza la elección aleatoria de tema |
| `weekly_focus_expires_at` | date, nullable | El portal la limpia sola después de la próxima generación — el engine no la borra, solo la lee |
| `drive_folder_id` | text | Carpeta del cliente dentro de la Unidad Compartida |
| `logo_url` | text, nullable | Ya existe como concepto en `main.py` (`cuan_logo.png`); acá es una URL |
| `calendly_link` | text, nullable | Ya existía en `CONFIG` de `main.py`, ahora por cliente |
| `prob_link` | float, default 0 | Ídem |

**`client_images`** (nueva) — tracking de no-repetición:
| Campo | Tipo |
|---|---|
| `id` | uuid pk |
| `client_id` | uuid fk |
| `drive_file_id` | text |
| `drive_file_name` | text |
| `last_used_at` | timestamptz, nullable |
| `times_used` | int, default 0 |

**`employee_clients`** (nueva) — asignación PM↔cliente:
| Campo | Tipo |
|---|---|
| `employee_id` | uuid fk |
| `client_id` | uuid fk |

**`prompt_history`** (nueva, recomendada) — auditoría del prompt evolutivo:
| Campo | Tipo |
|---|---|
| `id` | uuid pk |
| `client_id` | uuid fk |
| `changed_by` | uuid fk → employees |
| `field` | text — `'business_description'` \| `'weekly_focus'` \| `'tone_examples'` \| `'topics'` |
| `old_value` | text |
| `new_value` | text |
| `changed_at` | timestamptz |

**`teams`** (nueva, A5) — subdivisión de una agencia (varios empleados, varios clientes a su cargo), puramente organizativa para que a los empleados les sea más fácil encontrar sus clientes en el panel. No afecta el contrato del engine ni permisos:
| Campo | Tipo |
|---|---|
| `id` | uuid pk |
| `agency_id` | uuid fk → agencies |
| `name` | text, único por agencia |
| `created_at` | timestamptz |

`employees.team_id` y `clients.team_id` (ambos uuid, nullable, fk → `teams`, `on delete set null`) marcan a qué equipo pertenece cada uno.

---

## 3. Modelos de datos del contrato (viven en `app/engine/schemas.py`, Pydantic)

```python
class ClientContentConfig(BaseModel):
    client_id: str
    nombre_negocio: str
    business_description: str
    weekly_focus: str | None = None
    tone_examples: list[list[str]]      # cada item: las 4 historias de un hilo de ejemplo
    topics: list[str] | None = None
    logo_url: str | None = None
    calendly_link: str | None = None
    prob_link: float = 0.0              # probabilidad (0-1) de agregar el CTA en la historia 4, sorteada por el motor

class ImagenCandidata(BaseModel):
    drive_file_id: str
    drive_file_name: str
    image_bytes: bytes                  # el portal ya la bajó de Drive

class HiloGenerado(BaseModel):
    historias: list[str]                # 4 textos, en orden
    imagenes_originales_url: list[str]  # Cloudinary, SIN texto (para re-editar después)
    imagenes_editadas_url: list[str]    # Cloudinary, CON texto
    drive_file_ids_usados: list[str]    # el portal marca estos como last_used_at = ahora en client_images
    cta_agregado: bool = False          # si el motor efectivamente sorteó y dibujó el CTA (el portal NO debe re-sortear esto)

class ResultadoPublicacion(BaseModel):
    ok: bool
    ig_media_id: str | None = None
    error: str | None = None
```

## 4. Funciones públicas del motor (`app/engine/content.py`)

```python
def generar_hilo(config: ClientContentConfig, imagenes: list[ImagenCandidata]) -> HiloGenerado:
    """
    imagenes ya viene FILTRADO por no-repetición — el engine no sabe nada de
    "qué se usó hace 3 semanas", eso lo decide el portal antes de llamar acá.
    Debe recibir exactamente 4 imágenes. No escribe en ningún lado — devuelve
    los datos y el portal los persiste.
    Puede levantar EngineError si Claude falla o si faltan imágenes.
    """

def editar_historia(config: ClientContentConfig, imagen_original_bytes: bytes,
                     texto_nuevo: str, num_historia: int) -> str:
    """
    Re-edita UNA historia a partir de su imagen SIN texto (nunca de la ya editada).
    Devuelve la URL nueva de Cloudinary. Mismo truco que ya usa panel/app.py hoy.
    """

def generar_texto_de_prueba(config: ClientContentConfig, imagen: ImagenCandidata) -> list[str]:
    """
    Para el botón "Probar prompt" del panel: genera las 4 historias de texto
    pero NO sube nada a Cloudinary ni gasta nada más — solo texto, para que el
    PM vea el efecto de su edición antes de que salga en vivo.
    """

def publicar_historia(image_url: str, instagram_account_id: str, meta_access_token: str,
                       agregar_cta: bool, calendly_link: str | None) -> ResultadoPublicacion:
    """
    Publica UNA historia en Instagram. No decide cuándo — eso es de Celery/portal,
    que llama a esto una vez por historia del hilo del día.
    """
```

## 5. Quién hace qué, en la práctica

- El **portal** (Codex) consulta Drive, cruza contra `client_images.last_used_at` (excluye lo usado en las últimas N semanas, configurable), arma la lista de 4 `ImagenCandidata` y se la pasa al engine.
- El **engine** (Claude) nunca decide qué imagen usar por repetición — solo genera contenido con lo que le pasan.
- El **portal** escribe en `story_groups`/`stories`/`client_images`/`prompt_history` después de llamar al engine.
- El **portal** decide CUÁNDO llamar cada función: Celery beat semanal para `generar_hilo` (una vez por cliente activo, viernes), Celery task diaria para `publicar_historia` (una vez por historia pendiente del día).
- El **engine** son funciones sin estado — se pueden llamar en cualquier momento y con el mismo input dan el mismo resultado, salvo la llamada real a Claude (no determinística por diseño).
- Errores: el engine levanta excepciones tipadas (`EngineError` y subclases — `ClaudeGenerationError`, `ImageProcessingError`, `MetaPublishError`); el portal decide cómo reintentar/loguear, el engine no hace retry ni logging propio de negocio (sí puede loguear técnico a stdout).

## 6. Reglas de trabajo en git

- Worktree/rama separada por zona: `app/engine/**` es de Claude/Gonza, todo lo demás de Codex/Matías.
- PRs chicos. Cross-review recomendado: Codex revisa los PRs que tocan `app/engine`, y viceversa con lo que arme Codex — dos modelos revisando atrapan más que uno solo mirando su propio trabajo.
- Cualquier cambio de firma/tabla de este documento se negocia y se actualiza acá ANTES de escribir el código, no al revés.

## 7. Extensión del portal — Bloque A2

- La base existente usa `clients.active` y `clients.name`: el portal filtra `active = true` y mapea `name` a `ClientContentConfig.nombre_negocio`.
- `clients.generation_error` (text nullable) y `generation_error_at` (timestamptz nullable) exponen el último error de generación para B3; una generación persistida los limpia.
- `story_groups.status` admite también `pending`. `generation_week` (date nullable) identifica la semana generada; es única por cliente cuando está cargada, sin afectar grupos manuales.
- `stories` agrega `image_original_url` (text nullable), `fecha_publicacion` (date nullable), `estado` (text nullable: `pendiente`, `publicando`, `publicado`, `error`, `cancelada`), `error` (text nullable), `agregar_cta` (boolean default false) y `published_at` (timestamptz nullable). `cancelada` implementa el borrado blando desde el portal. Las filas anteriores conservan estado nulo y siguen el flujo existente.
- El hilo semanal tiene cuatro historias en orden 1–4, cada una con su propio `fecha_publicacion` repartido en la semana siguiente a la generación (lunes/miércoles/viernes/domingo — `PUBLISH_DAY_OFFSETS` en `content_jobs.py`), no las cuatro el mismo día. `story_groups.scheduled_date` guarda el primer día (el lunes) solo para agrupar/ordenar por semana. La publicación diaria corre a las 09:00 por defecto, configurable por entorno; todos los horarios usan America/Argentina/Buenos_Aires.
- La RPC `persist_generated_thread` (solo service_role) guarda grupo, cuatro historias y uso de imágenes en una transacción. Incrementa `times_used` atómicamente y limpia el foco solo si aún coincide con el texto y vencimiento utilizados; no consume un foco reemplazado durante la generación.
- `publicando` es un reclamo atómico antes de llamar a Meta, para evitar publicaciones duplicadas por workers concurrentes. Los errores no se reintentan automáticamente; un reclamo interrumpido requiere revisión manual antes de volver a pendiente.
- A2 toma las primeras cuatro imágenes de Drive. La lectura del historial y el filtro de no-repetición quedan para A3.
- El portal reordena historias mediante la RPC backend-only `reorder_stories`, que difiere la unicidad `(story_group_id, order)` durante el intercambio y valida que todas las filas pertenezcan al mismo grupo.
- El portal actualiza campos de prompt mediante la RPC backend-only `update_client_prompt`, que valida empleado y cliente contra la agencia esperada y guarda la actualización junto con sus filas de `prompt_history` en una única transacción.
