from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import _make_jwt


def test_portal_page_redirects_anonymous_employee_to_login():
    response = TestClient(app).get("/portal", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_portal_page_renders_authenticated_employee_shell():
    token = _make_jwt({
        "sub": "emp-1", "email": "pm@example.com", "name": "PM",
        "agency_id": "agency-1", "role": "employee",
    })
    response = TestClient(app).get("/portal", cookies={"session": token})

    assert response.status_code == 200
    assert 'id="client-list"' in response.text
    assert 'id="client-search"' in response.text
    assert 'id="business-description"' in response.text
    assert 'id="weekly-focus"' in response.text
    assert "Enfoque semanal" in response.text
    assert "pm@example.com" not in response.text
    assert "agency-1" not in response.text
    assert '<script src="/static/portal.js" defer></script>' in response.text


def test_portal_frontend_uses_real_api_without_prototype_data():
    response = TestClient(app).get("/static/portal.js")

    assert response.status_code == 200
    source = response.text
    assert "api(`/portal/clientes" in source
    assert "/probar-prompt" in source
    assert "PATCH" in source
    assert "DELETE" in source
    assert "/portal/historias/reordenar" in source
    assert "response.status === 401" in source
    assert "response.status === 403" in source
    assert "credentials: 'same-origin'" in source
    assert "selectionVersion" in source
    assert "clientId !== state.client?.id" in source
    assert "state.client = null" in source
    assert "clientSearch: ''" in source
    assert "toLocaleLowerCase('es')" in source
    assert "Sin resultados" in source
    assert "const STATUS_ORDER = {error: 0, pending: 1, ready: 2, idle: 3}" in source
    assert "$('client-search').addEventListener('input'" in source
    assert "CUAN Arquitectura" not in source
    assert "Panadería Dora" not in source
    assert "images.unsplash.com" not in source


def test_portal_frontend_keeps_health_dashboard_independent_and_latest_only():
    page = TestClient(app).get("/portal", cookies={"session": _make_jwt({
        "sub": "emp-1", "email": "pm@example.com", "name": "PM",
        "agency_id": "agency-1", "role": "employee",
    })})
    source = TestClient(app).get("/static/portal.js").text

    assert "Salud del sistema" in page.text
    assert 'id="home-health"' in page.text
    assert 'id="home-health-pill"' in page.text
    assert 'id="home-upcoming-panel"' in page.text
    assert 'id="home-idle-panel"' in page.text
    assert 'id="health-generacion"' not in page.text
    assert "homeSummaryVersion: 0" in source
    assert "const summaryVersion = ++state.homeSummaryVersion;" in source
    assert "Promise.allSettled([api('/portal/resumen'), api('/portal/salud')])" in source
    assert "summaryVersion !== state.homeSummaryVersion" in source
    assert "summaryResult.status === 'fulfilled'" in source
    assert "healthResult.status === 'fulfilled'" in source
    assert "renderHealthUnavailable()" in source
    assert "renderHomeUpcoming(summary.proximas_publicaciones);" in source


def test_portal_frontend_supports_variable_rhythm_and_keeps_all_pending_groups_active():
    page = TestClient(app).get("/portal", cookies={"session": _make_jwt({
        "sub": "emp-1", "email": "pm@example.com", "name": "PM",
        "agency_id": "agency-1", "role": "employee",
    })})
    source = TestClient(app).get("/static/portal.js").text

    assert "Elegí entre 1 y 4 días" in page.text
    assert 'id="generate-weekly"' in page.text
    assert 'id="ritmo-generation-message"' in page.text
    assert 'id="ritmo-days-detail"' in page.text
    assert 'id="ritmo-count-total"' in page.text
    assert 'id="save-ritmo-detail"' in page.text
    assert 'id="publish-together-toggle"' not in page.text
    assert "Elegí al menos un día de publicación." in source
    assert "/generar-semana" in source
    assert "button.textContent = 'Generando...'" in source
    assert "feedback.textContent = error.message" in source
    assert "function storyIsScheduled(story, group)" in source
    assert "if (!storyIsScheduled(story, group)) continue;" in source
    assert "if (storyIsScheduled(story, group)) continue;" in source
    assert "for (const g of state.groups)" in source
    assert "draftDates = new Set(); setControlsDisabled(true)" in source
    assert 'class="empty-state"' in source
    assert "data-empty-cta" in source
    assert "if (emptyCta) { openRitmoDialog(); return; }" in source


def test_generated_day_time_is_editable_and_uses_day_endpoint():
    source = TestClient(app).get("/static/portal.js").text

    assert 'class="day-time"' in source
    assert 'disabled title="Este día usa el horario de Editar ritmo"' not in source
    assert "/dias/${encodeURIComponent(iso)}/hora" in source
    assert "const operationKey = dayOperationKey(clientId, selectionVersion, iso)" in source
    assert "dayTimeSaving.has(operationKey)" in source
    assert "dayTimeSaving.add(operationKey)" in source
    assert "dayTimeSaving.delete(operationKey)" in source
    assert "const pendingDayTimes = new Map()" in source
    assert "pendingDayTimes.set(operationKey, hhmm)" in source
    assert "Always reload, including after an error" in source
    assert "A change that arrived while reloading must still be persisted" in source
    assert "retryValue = pendingDayTimes.get(operationKey) || null" in source
    assert "updateDayTime(iso, queued, input)" in source


def test_generated_day_can_publish_immediately_with_double_click_guard():
    source = TestClient(app).get("/static/portal.js").text

    assert "data-publish-now-date" in source
    assert "/publicar-ahora" in source
    assert "async function publishDayNow" in source
    assert "const publishingDates = new Set()" in source
    assert "publishingDates.has(operationKey)" in source
    assert "Esto publica de verdad en Instagram ahora mismo" in source
    assert "La publicación se realizó, pero no se pudo actualizar la pantalla" in source


def test_generated_day_actions_ignore_already_locked_stories():
    source = TestClient(app).get("/static/portal.js").text

    assert "const LOCKED_STORY_STATES = new Set(['publicando', 'publicado', 'cancelada'])" in source
    assert "const storyIsLocked = (story) => LOCKED_STORY_STATES.has(story?.estado)" in source
    assert "const actionableStories = stories.filter((story) => !storyIsLocked(story))" in source
    assert "actionableStories.length > 0 && actionableStories.every" in source
    assert "const batchReorderable = (group.stories || []).every((story) => !storyIsLocked(story))" in source
    assert "const mutationActions = locked ? ''" in source
    assert 'draggable="${reorderable ? \'true\' : \'false\'}"' in source
    assert "if (storyIsLocked(found.story)) return;" in source
    assert "if(card.dataset.reorderable!=='true' || !found || storyIsLocked(found.story))" in source
    assert "if ((group.stories || []).some((story) => storyIsLocked(story))) return;" in source
    assert "$('ig-preview-edit').classList.toggle('hidden', locked)" in source
    assert "$('ig-preview-delete').classList.toggle('hidden', locked)" in source
    assert "storiesForDay.some((story) => storyIsLocked(story))" in source
    assert "const addRow = dayLocked ? ''" in source


def test_plan_day_delete_is_unavailable_when_any_story_on_the_date_is_locked():
    source = TestClient(app).get("/static/portal.js").text

    assert "const canDelete = stories.every((story) => !storyIsLocked(story))" in source
    assert "const deleteButton = canDelete ?" in source
    assert "if (entry.stories.some((story) => storyIsLocked(story))) return;" in source


def test_batch_reorder_uses_every_story_in_the_group_for_lock_state():
    source = TestClient(app).get("/static/portal.js").text

    assert "const batchReorderable = (group.stories || []).every((story) => !storyIsLocked(story))" in source
    assert "const batchReorderable = batchStories.every" not in source


def test_publish_now_reappears_to_retry_failed_stories_but_not_mid_claim():
    source = TestClient(app).get("/static/portal.js").text

    assert "const retryableStories = stories.filter((story) => story.estado === 'pendiente' || story.estado === 'error')" in source
    assert "const publishNowBlocked = stories.some((story) => story.estado === 'publicando')" in source
    assert "retryableStories.length > 0 && !publishNowBlocked && retryableStories.every((story) => story.aprobado)" in source
    assert "const publishNowBtn = readyToPublishNow ?" in source
    assert "const hasFailedStory = stories.some((story) => story.estado === 'error')" in source
    assert "const retryBlocked = stories.some((story) => story.estado === 'publicando')" in source
    assert "const retryButton = canRetry ?" in source
    assert 'data-plan-retry="${escapeHtml(iso)}"' in source
    assert "publishDayNow(retryBtn.dataset.planRetry)" in source
    assert '[data-plan-retry="${CSS.escape(iso)}"]' in source


def test_portal_frontend_blocks_generation_during_any_rhythm_save():
    source = TestClient(app).get("/static/portal.js").text

    assert "let ritmoSaving = false" in source
    assert "let ritmoLoading = false" in source
    assert "function setRitmoSaving(saving)" in source
    assert source.count("setRitmoSaving(true)") == 2
    assert source.count("setRitmoSaving(false)") == 2
    assert "const rhythmControlsBlocked = ritmoLoading || ritmoSaving || weeklyGenerating" in source
    assert "document.querySelectorAll('#ritmo-days-detail input')" in source
    assert "$('save-ritmo-detail').disabled = ritmoSaving || weeklyGenerating" in source
    assert "$('generate-weekly').disabled = rhythmControlsBlocked" in source
    assert "classList.toggle('is-saving', rhythmControlsBlocked)" in source
    assert source.count("if (ritmoSaving || weeklyGenerating) return") == 3
    assert "const renderedTimes = new Map(ritmoDetailEntries().map" in source
    assert source.index("const renderedTimes = new Map") < source.index("const next = ritmoDays.map")
    assert "ritmoDays = [];" in source
    assert "if (ritmoLoading || !state.client) return;" in source


def test_portal_frontend_keeps_story_reordering_inside_its_group():
    source = TestClient(app).get("/static/portal.js").text

    assert 'data-story-group-id="${escapeHtml(groupId)}"' in source
    assert "draggedStoryGroupId=card.dataset.storyGroupId" in source
    assert "card.dataset.storyGroupId !== draggedStoryGroupId" in source
    assert "Generación IA" in source
    assert "Carga manual" in source


def test_static_assets_are_never_cached_in_development():
    # portal.js/portal.html change every few minutes during dev and are
    # served fresh from disk under the same URL every time — without this,
    # a browser can keep running a stale cached copy after an edit.
    response = TestClient(app).get("/static/portal.js")

    assert response.headers.get("cache-control") == "no-store"


def test_engine_fonts_are_served_read_only_for_the_font_previews():
    # Same files app.engine.imaging composes with server-side, exposed
    # so the portal's typography pickers can preview each option live.
    response = TestClient(app).get("/fonts/Raleway%5Bwght%5D.ttf")

    assert response.status_code == 200
    assert response.headers["content-type"] in ("font/ttf", "application/font-sfnt", "application/octet-stream")
