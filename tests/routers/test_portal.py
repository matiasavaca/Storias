from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.deps import require_employee
from app.main import app
from app.models.user import Employee


@dataclass
class Result:
    data: object


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.payload = None
        self.is_maybe_single = False

    def select(self, *args, **kwargs): return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def in_(self, key, values): self.filters.append((key, list(values))); return self
    def gte(self, key, value): self.filters.append((key, value)); return self
    def neq(self, key, value): self.filters.append((key, value)); return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def maybe_single(self): self.is_maybe_single = True; return self
    def update(self, payload): self.payload = payload; self.db.updates.append((self.table, payload, self.filters)); return self
    def insert(self, payload): self.payload = payload; self.db.inserts.append((self.table, payload)); return self
    def execute(self):
        value = self.db.responses.pop(0)
        # Real postgrest-py's maybe_single() returns None outright (not a
        # response with data=None) on zero rows — let tests simulate that.
        if self.is_maybe_single and value is None:
            return None
        return Result(value)


class DB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.updates = []
        self.inserts = []

    def table(self, name): return Query(self, name)

    def rpc(self, name, payload):
        self.inserts.append((f"rpc:{name}", payload))
        return Query(self, f"rpc:{name}")


@pytest.fixture
def employee():
    return Employee(id="emp-1", email="pm@example.com", name="PM", agency_id="agency-1", role="employee")


@pytest.fixture
def client(employee):
    app.dependency_overrides[require_employee] = lambda: employee
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_me_reports_current_employee_including_team(monkeypatch, client):
    response = client.get("/portal/me")
    assert response.status_code == 200
    assert response.json() == {"id": "emp-1", "name": "PM", "email": "pm@example.com",
                                "role": "employee", "agency_id": "agency-1", "team_id": None}


def test_list_teams_scopes_to_employee_agency(monkeypatch, client):
    db = DB([[{"id": "t1", "name": "Equipo A"}, {"id": "t2", "name": "Equipo B"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/equipos")
    assert response.status_code == 200
    assert response.json() == [{"id": "t1", "name": "Equipo A"}, {"id": "t2", "name": "Equipo B"}]


def test_history_flattens_employee_name_and_requires_agency_match(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [
        {"id": "h1", "field": "business_description", "old_value": "a", "new_value": "b",
         "changed_at": "2026-01-01T00:00:00Z", "changed_by": "emp-1", "employees": {"name": "PM"}},
    ]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes/c1/historial")
    assert response.status_code == 200
    assert response.json() == [{"id": "h1", "field": "business_description", "old_value": "a",
        "new_value": "b", "changed_at": "2026-01-01T00:00:00Z", "changed_by": "emp-1", "changed_by_name": "PM"}]


def test_create_team_inserts_scoped_to_agency(monkeypatch, client):
    db = DB([[{"id": "t1", "agency_id": "agency-1", "name": "Equipo Nuevo"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.post("/portal/equipos", json={"name": "Equipo Nuevo"})
    assert response.status_code == 200
    assert response.json()["name"] == "Equipo Nuevo"
    assert db.inserts == [("teams", {"agency_id": "agency-1", "name": "Equipo Nuevo"})]


def test_create_team_rejects_duplicate_name(monkeypatch, client):
    class ConflictingDB:
        def table(self, name):
            class Q:
                def insert(self, payload):
                    def execute():
                        raise APIError({"message": "duplicate", "code": "23505", "details": None, "hint": None})
                    return SimpleNamespace(execute=execute)
            return Q()
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: ConflictingDB())
    response = client.post("/portal/equipos", json={"name": "Equipo Repetido"})
    assert response.status_code == 409


def test_patch_client_team_validates_team_belongs_to_agency(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, {"id": "t1"}, [{"id": "c1", "team_id": "t1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/equipo", json={"team_id": "t1"})
    assert response.status_code == 200
    assert response.json()["team_id"] == "t1"
    assert db.updates == [("clients", {"team_id": "t1"}, [("id", "c1")])]


def test_patch_client_team_rejects_team_from_another_agency(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/equipo", json={"team_id": "foreign-team"})
    assert response.status_code == 422
    assert db.updates == []


def test_patch_client_team_can_unassign(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "c1", "team_id": None}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/equipo", json={"team_id": None})
    assert response.status_code == 200
    assert db.updates == [("clients", {"team_id": None}, [("id", "c1")])]


def test_list_clients_defaults_to_entire_agency(monkeypatch, client):
    db = DB([[{"id": "c1", "agency_id": "agency-1"}, {"id": "c2", "agency_id": "agency-1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["c1", "c2"]


def test_list_clients_can_filter_to_employee_assignments(monkeypatch, client):
    db = DB([[{"client_id": "c2"}], [{"id": "c2", "agency_id": "agency-1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes?solo_mios=true")
    assert response.status_code == 200
    assert response.json() == [{"id": "c2", "agency_id": "agency-1"}]


def test_missing_client_is_404_not_a_crash_when_postgrest_returns_none(monkeypatch, client):
    # Regression: real postgrest-py's maybe_single() returns None outright
    # (not a response object) on zero rows, unlike the naive mocks elsewhere.
    db = DB([None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes/missing")
    assert response.status_code == 404


def test_edit_missing_story_is_404_not_a_crash_when_postgrest_returns_none(monkeypatch, client):
    db = DB([None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/missing", json={"texto_nuevo": "updated"})
    assert response.status_code == 404


def test_client_from_other_agency_is_forbidden(monkeypatch, client):
    db = DB([{"id": "foreign", "agency_id": "agency-2"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes/foreign")
    assert response.status_code == 403


def test_patch_client_audits_each_changed_prompt_field(monkeypatch, client):
    db = DB([{
        "id": "c1", "agency_id": "agency-1", "business_description": "old",
        "weekly_focus": None, "weekly_focus_expires_at": None,
        "tone_examples": [["a", "b", "c", "d"]], "topics": ["old-topic"],
    }, {"id": "c1", "business_description": "new", "topics": ["new-topic"]}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1", json={"business_description": "new", "topics": ["new-topic"]})
    assert response.status_code == 200
    rpc = next(payload for table, payload in db.inserts if table == "rpc:update_client_prompt")
    assert rpc == {"p_client_id": "c1", "p_employee_id": "emp-1", "p_agency_id": "agency-1",
                   "p_patch": {"business_description": "new", "topics": ["new-topic"]}}
    assert db.updates == []


def test_patch_client_serializes_focus_expiration_for_supabase(monkeypatch, client):
    db = DB([{
        "id": "c1", "agency_id": "agency-1", "business_description": "desc",
        "weekly_focus": None, "weekly_focus_expires_at": None,
        "tone_examples": [], "topics": [],
    }, {"id": "c1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1", json={
        "weekly_focus": "launch", "weekly_focus_expires_at": "2026-09-30",
    })
    assert response.status_code == 200
    rpc = next(payload for table, payload in db.inserts if table == "rpc:update_client_prompt")
    assert rpc["p_patch"]["weekly_focus_expires_at"] == "2026-09-30"


def test_patch_client_rejects_null_tone_examples_before_database(monkeypatch, client):
    factory = SimpleNamespace(called=False)
    def database():
        factory.called = True
        return DB([])
    monkeypatch.setattr("app.routers.portal.get_admin_client", database)

    response = client.patch("/portal/clientes/c1", json={"tone_examples": None})

    assert response.status_code == 422
    assert factory.called is False


def test_try_prompt_reads_first_drive_image_without_database_writes(monkeypatch, client):
    row = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
           "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
           "calendly_link": None, "prob_link": 0, "drive_folder_id": "folder"}
    db = DB([row])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_images", lambda _: pytest.fail("must not download full pool"))
    monkeypatch.setattr("app.routers.portal.drive.first_image", lambda _: ("f1", "one.jpg", b"image"))
    seen = {}
    def generate(config, image):
        seen["id"] = image.drive_file_id
        return ["one", "two", "three", "four"]
    monkeypatch.setattr("app.routers.portal.content.generar_texto_de_prueba", generate)
    response = client.post("/portal/clientes/c1/probar-prompt")
    assert response.json() == {"historias": ["one", "two", "three", "four"]}
    assert seen == {"id": "f1"}
    assert db.updates == [] and db.inserts == []


def test_calendar_keeps_legacy_null_state_and_excludes_cancelled(monkeypatch, client):
    groups = [{"id": "g1", "stories": [
        {"id": "legacy", "estado": None}, {"id": "pending", "estado": "pendiente"},
        {"id": "cancelled", "estado": "cancelada"},
    ]}]
    db = DB([{"id": "c1", "agency_id": "agency-1"}, groups])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes/c1/historias")
    assert response.status_code == 200
    assert [story["id"] for story in response.json()[0]["stories"]] == ["legacy", "pending"]


def test_edit_story_uses_original_image_and_updates_edited_url(monkeypatch, client):
    story = {"id": "s1", "client_id": "c1", "order": 2, "image_url": "https://edited",
             "image_original_url": "https://original"}
    config = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
              "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
              "calendly_link": None, "prob_link": 0}
    db = DB([story, config, [{"id": "s1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda url, timeout: SimpleNamespace(content=b"original", raise_for_status=lambda: None))
    called = {}
    def edit(cfg, image, text, number): called.update(image=image, text=text, number=number); return "https://new"
    monkeypatch.setattr("app.routers.portal.content.editar_historia", edit)
    response = client.patch("/portal/historias/s1", json={"texto_nuevo": "updated"})
    assert response.status_code == 200
    assert called == {"image": b"original", "text": "updated", "number": 2}
    assert db.updates[-1][1] == {"text": "updated", "image_url": "https://new"}


def test_reorder_updates_only_requested_stories(monkeypatch, client):
    stories = [{"id": "s1", "story_group_id": "g1", "client_id": "c1"}, {"id": "s2", "story_group_id": "g1", "client_id": "c1"}]
    db = DB([stories, {"id": "c1", "agency_id": "agency-1"}, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/reordenar", json={"historias": [{"story_id": "s1", "nuevo_order": 2}, {"story_id": "s2", "nuevo_order": 1}]})
    assert response.status_code == 200
    assert ("rpc:reorder_stories", {"p_orders": [{"story_id": "s1", "new_order": 2}, {"story_id": "s2", "new_order": 1}]}) in db.inserts


def test_reorder_translates_stale_group_rpc_error_into_conflict(monkeypatch, client):
    stories = [{"id": "s1", "story_group_id": "g1", "client_id": "c1"}, {"id": "s2", "story_group_id": "g1", "client_id": "c1"}]
    db = DB([stories, {"id": "c1", "agency_id": "agency-1"}])

    def raise_stale(name, payload):
        raise APIError({"message": "stale group", "code": "P0001", "details": None, "hint": None})

    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr(db, "rpc", raise_stale)
    response = client.patch("/portal/historias/reordenar", json={"historias": [{"story_id": "s1", "nuevo_order": 2}, {"story_id": "s2", "nuevo_order": 1}]})
    assert response.status_code == 409


def test_reorder_rejects_stories_from_different_groups(monkeypatch, client):
    stories = [{"id": "s1", "story_group_id": "g1", "client_id": "c1"}, {"id": "s2", "story_group_id": "g2", "client_id": "c1"}]
    db = DB([stories])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/reordenar", json={"historias": [{"story_id": "s1", "nuevo_order": 2}, {"story_id": "s2", "nuevo_order": 1}]})
    assert response.status_code == 422
    assert db.updates == [] and db.inserts == []


def test_cancel_story_is_soft_delete_after_agency_check(monkeypatch, client):
    db = DB([{"id": "s1", "client_id": "c1", "estado": "pendiente"}, {"id": "c1", "agency_id": "agency-1"}, [{"id": "s1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.delete("/portal/historias/s1")
    assert response.status_code == 200
    assert db.updates == [("stories", {"estado": "cancelada"}, [("id", "s1")])]


@pytest.mark.parametrize("estado", ["publicando", "publicado", "cancelada"])
def test_edit_story_already_published_or_cancelled_is_rejected(monkeypatch, client, estado):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original", "estado": estado}
    db = DB([story, {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda *a, **k: pytest.fail("must not re-render a locked story"))
    response = client.patch("/portal/historias/s1", json={"texto_nuevo": "updated"})
    assert response.status_code == 409
    assert db.updates == []


@pytest.mark.parametrize("estado", ["publicando", "publicado", "cancelada"])
def test_cancel_story_already_published_or_cancelled_is_rejected(monkeypatch, client, estado):
    db = DB([{"id": "s1", "client_id": "c1", "estado": estado}, {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.delete("/portal/historias/s1")
    assert response.status_code == 409
    assert db.updates == []


def test_edit_story_from_other_agency_is_forbidden_before_download(monkeypatch, client):
    story = {"id": "s1", "client_id": "foreign", "order": 1, "image_original_url": "https://original"}
    db = DB([story, {"id": "foreign", "agency_id": "agency-2"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda *args, **kwargs: pytest.fail("must not download"))
    response = client.patch("/portal/historias/s1", json={"texto_nuevo": "updated"})
    assert response.status_code == 403
    assert db.updates == []


def test_portal_requires_employee_auth():
    response = TestClient(app).get("/portal/clientes")
    assert response.status_code == 401
