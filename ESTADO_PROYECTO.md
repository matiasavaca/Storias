# Estado del proyecto — Portal Storias / Argo Media

Última actualización: 2026-09-16 (Gonza). Este documento es para que Matías retome el trabajo sin tener que preguntar por WhatsApp qué se hizo — se actualiza cada vez que se cierra un bloque. El contrato técnico completo (tablas, modelos Pydantic, firmas de función) sigue viviendo en `AGENTS.md`/`CLAUDE.md` en la raíz del repo — esto es el resumen humano de qué se hizo y qué falta.

## Dónde está el código

- Rama de trabajo: `codex/a2-engine-integration` (tiene adentro A1 + A2 + A3, ver abajo). Todavía no está mergeada a `main`.
- Si estás leyendo esto desde un fork (`github.com/GonzaBermudezz/Storias`), es porque Gonza todavía no tenía tu usuario como colaborador en `matiasavaca/Storias` al momento de hacer este trabajo — pediselo si no lo tenés, así se puede laburar directo sobre el repo original de acá en adelante.

## Qué se hizo, bloque por bloque

**A1 — Motor de contenido multi-cliente (listo, commit `12b117c`)**
Se sacó de `main.py` (el bot original de Cuan) todo lo que estaba hardcodeado para un solo cliente y pasó a `app/engine/`, que ahora recibe todo por parámetro (`ClientContentConfig`):
- `app/engine/schemas.py`, `exceptions.py`, `content.py`, `imaging.py`.
- `CLAUDE_MODEL = "claude-sonnet-5"` reemplaza el `"claude-sonnet-4-6"` original (no era un modelo válido).
- 17 tests verdes con los valores reales de CUAN como fixture, mockeando Claude/Cloudinary/Meta.
- El motor no importa nada de Supabase/Celery/Drive/FastAPI — es la regla dura del contrato.

**A2 — Cola de trabajo y scheduler (listo)**
Conecta el motor de A1 con el resto del sistema:
- Migración SQL: columnas nuevas en `clients` + tablas `client_images`, `employee_clients`, `prompt_history`.
- `app/services/drive.py`: integración con Google Drive (Shared Drives).
- `app/services/content_jobs.py`: generación semanal por cliente, aislando errores (un cliente con problemas no frena a los demás).
- `app/services/scheduler.py`: tareas de Celery — generación viernes 18:00, publicación diaria (configurable, default 09:00).
- 33 tests Python + 10 grupos de validación SQL (PGlite) en verde.
- **Pendiente**: la migración todavía no se aplicó a un Supabase real — no hay proyecto de Supabase creado todavía (es parte de la A0, ver abajo).

**A3 — No-repetición real de imágenes entre semanas (listo, verificado)**
- `seleccionar_imagenes(...)` prioriza: (1) imágenes nunca usadas, (2) imágenes fuera del cooldown, (3) si el pool está agotado, recicla las más antiguas (`last_used_at` más viejo primero) en vez de frenar la generación.
- `NO_REPEAT_WEEKS = 3` queda centralizado y configurable en un solo lugar.
- `generate_weekly()` ahora lee `client_images` antes de seleccionar (reemplaza el `TODO(A3)`) y persiste la advertencia `pool_bajo` cuando recicla, con marcador `TODO(B3)` para el futuro dashboard de salud.
- Confirmado: `app/engine/**`, migraciones y auth sin modificar.

**Suite completa verificada de punta a punta: `python -m pytest` en `C:\Storias` → 36/36 tests en verde** (17 de A1 + los de A2 + los de A3, corridos juntos en un estado limpio, con `pip install -r requirements.txt` recién hecho). Nota para quien corra esto de nuevo: usar `python -m pytest`, no `pytest` solo — con el comando `pytest` a secas da `ModuleNotFoundError: No module named 'app'` en este entorno.

## A0 — Infraestructura real (lista para desarrollo/piloto)

- Proyecto de Supabase real creado, schema + migración de A2 aplicados.
- Carpeta de Drive normal (no Unidad Compartida todavía — ver nota abajo) compartida con una service account, `GOOGLE_SERVICE_ACCOUNT_FILE` configurado, scope `drive.readonly`.
- Claude, Cloudinary y clave de encriptación cargados en `.env`.
- **Smoke test real de punta a punta corrido con éxito el 2026-09-15** (`scratchpad/smoke_real_a3.py`, no commiteado — script de un solo uso): bajó 4 imágenes reales de Drive, Claude generó 4 historias reales con el prompt de CUAN, se subieron 8 URLs reales a Cloudinary (4 crudas + 4 editadas), y quedó persistido en Supabase (`story_group` + 4 `stories` + 4 filas en `client_images`). Cero errores. **Confirma que A1+A2+A3 funcionan juntos contra servicios reales, no solo en tests mockeados.**
- Queda un cliente de prueba real en la tabla `clients` (`CUAN A3 Real Smoke...`, id `628e4d79-f55c-4f1b-9210-f28f77777b2b`) — decidir si se borra o se deja de referencia antes de sumar clientes reales de Felix.
- **Nota**: por ahora la carpeta de Drive es una carpeta común (no Unidad Compartida), porque el plan de Google Workspace de Argo Media todavía no está confirmado — ver sección de decisiones abajo. Migrar a Unidad Compartida antes de sumar clientes reales de producción.

## A4a — API del portal de empleados (lista, verificada)

- `app/routers/portal.py`: listado de clientes, detalle, edición de prompt (con auditoría atómica en `prompt_history`), "probar prompt" (sin efectos secundarios — no sube nada a Cloudinary ni escribe en Supabase), listado/edición/reorden/cancelación de historias.
- **Acceso por agencia, no por asignación individual**: cualquier empleado ve y edita cualquier cliente de su misma `agency_id` (decisión de Gonza — los PMs de Felix rotan de cliente seguido). `employee_clients` sigue existiendo solo como filtro opcional `?solo_mios=true`, no como restricción dura.
- Edición de historias usa siempre `image_original_url` (nunca la ya editada).
- Reordenamiento transaccional y cancelación lógica de historias (no borrado físico) vía `migrations/20260915_a4_portal_cancelled_stories.sql`.
- Sin cambios en `app/engine/**`, auth ni el mockup HTML.
- **51/51 tests en verde** (`python -m pytest`) + 4/4 checks de validación PostgreSQL.
- **Amendment (A4b, 2026-09-16)**: al cablear el frontend, Codex encontró un bug real en `reorder_stories` (el reorden no era consistente cuando había historias canceladas de por medio) y lo corrigió en la misma migración `migrations/20260915_a4_portal_cancelled_stories.sql`. **Importante**: si ya aplicaste esta migración en tu Supabase real (parte de A0), hay que volver a correrla para actualizar la función `reorder_stories` con el fix.

## A4b — Portal conectado a la API real (listo, verificado)

- El mockup `opcion2-empleados.html` dejó de ser un prototipo con datos hardcodeados: ahora es la página real de la app, servida en `/portal` detrás de la auth de empleado (no accesible sin login).
- Sidebar de clientes, filtro `solo_mios`, descripción del negocio, enfoque semanal (`weekly_focus`, repurposeando el chip de "objetivo del contenido" del mockup original), "probar prompt", edición/reorden/cancelación de historias: todo dispara la llamada real correspondiente a `app/routers/portal.py`.
- Manejo de 401 (redirige a login) y 403 (mensaje claro) sin romper la página. Loading states mínimos mientras esperan respuesta real.
- Fix de una condición de carrera: respuestas tardías de `fetch` ya no pueden pisar/sobrescribir el cliente seleccionado si el usuario cambió de cliente mientras tanto.
- Reordenar después de cancelar una historia funciona de forma atómica (ver amendment de A4a arriba — requirió tocar la función SQL `reorder_stories`).
- **54/54 tests en verde** (`python -m pytest`) + 4/4 validación SQL + `node --check static/portal.js` sin errores.
- **Verificación visual en curso (2026-09-16)**: al probar el login real en local, aparecieron 3 problemas de setup/código, ya resueltos:
  1. `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` habían quedado con el valor placeholder del `.env.example` — nunca se había creado el OAuth Client ID real en Google Cloud (proyecto `stories-argomedia`). Se creó la pantalla de consentimiento + credencial OAuth (Web application, redirect URI `http://localhost:5001/auth/callback`) y se cargaron las credenciales reales.
  2. El proyecto de Supabase (free tier) estaba dormido por inactividad — un 522 de Cloudflare en el primer request lo "despertó"; quedó healthy después.
  3. **Bug real de código, corregido**: `app/main.py` registraba `SessionMiddleware` (Starlette, para el `oauth_state` del login) sin `session_cookie=...`, por lo que usaba el nombre por defecto `"session"` — el mismo nombre que `_set_session_cookie()` en `app/routers/auth.py` usa para la cookie de sesión del empleado. Ambos pisaban la misma cookie en la respuesta del callback: el middleware, al vaciar `oauth_state` con `.pop()`, mandaba un `Set-Cookie` que borraba la cookie de login que el propio endpoint acababa de setear, generando un loop infinito `/portal → /login → /auth/google`. Fix aplicado a mano en `app/main.py`: `app.add_middleware(SessionMiddleware, secret_key=s.secret_key, https_only=s.is_production, session_cookie="oauth_session")`. Con las tres cosas resueltas, el login + `/portal` funcionan de punta a punta (falta solo la revisión visual del resto del flujo — editar/guardar/reordenar — con datos reales cargados).
  - Se creó la agencia real `Argo Media` (tabla `agencies`) y a Gonza como primer empleado (`employees`, email `gonza.bermudez98@gmail.com`, role `admin`) para poder loguearse — la agencia todavía no tiene clientes asociados.

## Qué NO está hecho todavía
- **A5 — Piloto end-to-end**: 2-3 clientes reales de Felix corriendo un ciclo semanal completo.
- Fase B completa (conexión de Instagram self-serve con Facebook Login for Business — depende de que Felix haya iniciado el trámite de App Review de Meta —, alta masiva de clientes, dashboard de salud del sistema, rollout gradual).

## Decisiones ya tomadas (no reabrir sin avisar)

- Sin aprobación del cliente antes de publicar — se genera y publica solo.
- Los PMs de Felix manejan las cuentas de Instagram de sus clientes (no hay OAuth de cliente final en el MVP).
- Un solo Google Drive (Unidad Compartida) para toda Argo Media, una carpeta por cliente.
- `NO_REPEAT_WEEKS = 3` como default de no-repetición (fácil de cambiar, ver A3).

## Próximo paso sugerido para quien retome esto

Si sos Matías y estás leyendo esto: A0 a A4b ya están hechos y probados (infra real conectada, motor, cola de trabajo, no-repetición, API del portal y el portal ya conectado a esa API de verdad). **Antes de nada, si tu Supabase ya tenía la migración de A4 aplicada, volvé a correr `migrations/20260915_a4_portal_cancelled_stories.sql`** — A4b le agregó un fix a la función `reorder_stories`. Lo que sigue es la verificación visual de Gonza en `/portal`, y después A5 (piloto end-to-end con 2-3 clientes reales de Felix).