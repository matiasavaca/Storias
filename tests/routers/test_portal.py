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
    def is_(self, key, value): self.filters.append((key, value)); return self
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


def test_summary_reports_zero_state_with_no_clients(monkeypatch, client):
    db = DB([[]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/resumen")
    assert response.status_code == 200
    assert response.json() == {
        "historias_publicadas": 0, "historias_en_edicion": 0, "historias_agendadas": 0,
        "clientes_count": 0, "promedio_por_cliente": 0, "aprobacion_pct": None,
        "clientes_sin_actividad": [], "por_equipo": [],
    }


def test_summary_aggregates_published_upcoming_and_team_breakdown(monkeypatch, client):
    clients = [{"id": "c1", "name": "Cliente Uno", "team_id": "t1"},
               {"id": "c2", "name": "Cliente Dos", "team_id": "t1"},
               {"id": "c3", "name": "Cliente Tres", "team_id": None}]
    published = [{"id": "s1"}, {"id": "s2"}]
    upcoming = [{"client_id": "c1", "aprobado": True}, {"client_id": "c1", "aprobado": False},
                {"client_id": "c2", "aprobado": True}]
    teams = [{"id": "t1", "name": "Equipo A"}]
    db = DB([clients, published, upcoming, teams])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/resumen")
    assert response.status_code == 200
    body = response.json()
    assert body["historias_publicadas"] == 2
    assert body["historias_en_edicion"] == 1
    assert body["historias_agendadas"] == 2
    assert body["clientes_count"] == 3
    assert body["promedio_por_cliente"] == 1.0
    assert body["aprobacion_pct"] == 66.7
    assert body["clientes_sin_actividad"] == [{"id": "c3", "name": "Cliente Tres"}]
    assert body["por_equipo"] == [
        {"team_id": None, "team_name": "Sin equipo", "clientes": 1, "historias_en_edicion": 0, "historias_agendadas": 0, "aprobacion_pct": None},
        {"team_id": "t1", "team_name": "Equipo A", "clientes": 2, "historias_en_edicion": 1, "historias_agendadas": 2, "aprobacion_pct": 66.7},
    ]


def test_patch_client_ritmo_saves_four_distinct_days(monkeypatch, client):
    saved_days = [{"day": 1, "time": "08:00"}, {"day": 3, "time": "12:00"},
                  {"day": 5, "time": "18:00"}, {"day": 6, "time": "20:00"}]
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "c1", "publish_days": saved_days}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    unsorted = [saved_days[3], saved_days[0], saved_days[1], saved_days[2]]
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": unsorted})
    assert response.status_code == 200
    assert response.json()["publish_days"] == saved_days
    assert db.updates == [("clients", {"publish_days": saved_days}, [("id", "c1")])]


def test_patch_client_ritmo_rejects_non_distinct_days(monkeypatch, client):
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": [
        {"day": 1, "time": "08:00"}, {"day": 1, "time": "09:00"},
        {"day": 3, "time": "08:00"}, {"day": 5, "time": "08:00"}]})
    assert response.status_code == 422


def test_patch_client_ritmo_rejects_bad_time_format(monkeypatch, client):
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": [
        {"day": 1, "time": "25:00"}, {"day": 2, "time": "08:00"},
        {"day": 3, "time": "08:00"}, {"day": 5, "time": "08:00"}]})
    assert response.status_code == 422


def test_default_ritmo_reports_global_offsets(client):
    response = client.get("/portal/ritmo-default")
    assert response.status_code == 200
    assert response.json() == {"publish_days": [
        {"day": 0, "time": "09:00"}, {"day": 2, "time": "09:00"},
        {"day": 4, "time": "09:00"}, {"day": 6, "time": "09:00"}]}


def test_list_font_choices_reports_all_bundled_fonts(client):
    from app.engine.imaging import _FONT_FILES, FONT_CHOICES
    response = client.get("/portal/tipografias")
    assert response.status_code == 200
    assert response.json() == [
        {"key": k, "label": v, "file": _FONT_FILES[k]} for k, v in FONT_CHOICES.items()
    ]
    assert len(response.json()) == 20


def test_patch_client_font_saves_choice(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "c1", "font_choice": "poppins"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/tipografia", json={"font_choice": "poppins"})
    assert response.status_code == 200
    assert response.json()["font_choice"] == "poppins"
    assert db.updates == [("clients", {"font_choice": "poppins"}, [("id", "c1")])]


def test_patch_client_font_allows_clearing_to_null(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "c1", "font_choice": None}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/tipografia", json={"font_choice": None})
    assert response.status_code == 200
    assert db.updates == [("clients", {"font_choice": None}, [("id", "c1")])]


def test_patch_client_font_rejects_unknown_key(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/tipografia", json={"font_choice": "comic-sans"})
    assert response.status_code == 422
    assert db.updates == []


def test_create_manual_story_creates_group_and_first_story(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [], [{"id": "g1"}], [{"id": "s1", "order": 1}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag: "https://cdn/img.jpg")
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 200
    assert response.json() == {"id": "s1", "order": 1}
    group_insert = next(p for t, p in db.inserts if t == "story_groups")
    assert group_insert["scheduled_date"] == "2026-09-25" and group_insert["scheduled_time"] == "10:00:00"
    story_insert = next(p for t, p in db.inserts if t == "stories")
    assert story_insert["image_url"] == "https://cdn/img.jpg" and story_insert["order"] == 1
    assert story_insert["fecha_publicacion"] == "2026-09-25" and story_insert["hora_publicacion"] == "10:00:00"
    assert story_insert["aprobado"] is False


def test_create_manual_story_starts_a_fresh_group_when_the_existing_one_is_agendado(monkeypatch, client):
    # The group lookup filters on agendado = False, so an already-scheduled
    # group for that date never matches — a brand new group is created
    # instead of silently reopening a confirmed one.
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [], [{"id": "g2"}], [{"id": "s1", "order": 1}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag: "https://cdn/img.jpg")
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-21", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 200
    group_insert = next(p for t, p in db.inserts if t == "story_groups")
    assert group_insert["scheduled_date"] == "2026-09-21"
    story_insert = next(p for t, p in db.inserts if t == "stories")
    assert story_insert["story_group_id"] == "g2" and story_insert["order"] == 1


def test_create_manual_story_adds_to_existing_manual_group_on_same_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1"}], [{"order": 2}], [{"id": "s2", "order": 3}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag: "https://cdn/img2.jpg")
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 200
    story_insert = next(p for t, p in db.inserts if t == "stories")
    assert story_insert["order"] == 3 and story_insert["story_group_id"] == "g1"
    assert not any(t == "story_groups" for t, _ in db.inserts)


def test_create_manual_story_rejects_invalid_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "not-a-date", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 422
    assert db.inserts == []


def test_create_manual_story_surfaces_upload_errors(monkeypatch, client):
    from app.services import uploads
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    def boom(data, client_id, tag): raise uploads.UploadError("El archivo no es una imagen válida.")
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", boom)
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"not-an-image", "image/jpeg")})
    assert response.status_code == 422
    assert db.inserts == []


def test_approve_story_toggles_flag(monkeypatch, client):
    db = DB([{"id": "s1", "client_id": "c1", "estado": "pendiente"},
              {"id": "c1", "agency_id": "agency-1"}, [{"id": "s1", "aprobado": True}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/s1/aprobar", json={"aprobado": True})
    assert response.status_code == 200
    assert response.json()["aprobado"] is True
    assert db.updates == [("stories", {"aprobado": True}, [("id", "s1")])]


def test_approve_story_rejects_locked_state(monkeypatch, client):
    db = DB([{"id": "s1", "client_id": "c1", "estado": "publicado"},
              {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/s1/aprobar", json={"aprobado": True})
    assert response.status_code == 409


def test_approve_story_not_found(monkeypatch, client):
    db = DB([None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/missing/aprobar", json={"aprobado": True})
    assert response.status_code == 404


def test_update_manual_day_time_updates_group_and_editable_stories(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},                # client lookup
              [{"id": "g1"}],                                       # manual group lookup
              None,                                                 # story_groups update
              [{"id": "s1", "estado": "pendiente"}, {"id": "s2", "estado": "publicado"}],  # stories lookup
              None])                                                # stories update
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/hora",
        json={"hora_publicacion": "14:30"})
    assert response.status_code == 200
    assert response.json() == {"detail": "Hora actualizada", "updated": 1}
    group_update = next(u for u in db.updates if u[0] == "story_groups")
    assert group_update[1] == {"scheduled_time": "14:30:00"}
    stories_update = next(u for u in db.updates if u[0] == "stories")
    assert stories_update[1] == {"hora_publicacion": "14:30:00"}
    assert stories_update[2] == [("id", ["s1"])]


def test_update_manual_day_time_rejects_bad_format(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/hora",
        json={"hora_publicacion": "25:00"})
    assert response.status_code == 422


def test_update_manual_day_time_requires_existing_manual_group(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/hora",
        json={"hora_publicacion": "14:30"})
    assert response.status_code == 404


def test_update_manual_day_description_saves_note(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1"}],
              [{"id": "g1", "descripcion": "Proceso creativo"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/descripcion",
        json={"descripcion": "Proceso creativo"})
    assert response.status_code == 200
    assert response.json()["descripcion"] == "Proceso creativo"
    assert db.updates == [("story_groups", {"descripcion": "Proceso creativo"}, [("id", "g1")])]


def test_update_manual_day_description_clears_with_null(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1"}],
              [{"id": "g1", "descripcion": None}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/descripcion",
        json={"descripcion": ""})
    assert response.status_code == 200
    assert db.updates == [("story_groups", {"descripcion": None}, [("id", "g1")])]


def test_update_manual_day_description_requires_existing_manual_group(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/descripcion",
        json={"descripcion": "algo"})
    assert response.status_code == 404


def test_schedule_day_succeeds_when_all_approved(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "s1", "estado": "pendiente", "aprobado": True, "story_group_id": "g1"},
               {"id": "s2", "estado": "pendiente", "aprobado": True, "story_group_id": "g1"}],
              None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200
    assert response.json() == {"detail": "Publicación agendada"}
    assert db.updates == [("story_groups", {"agendado": True}, [("id", "g1")])]


def test_schedule_day_bundles_every_group_sharing_that_date(monkeypatch, client):
    # A day can be published from an AI batch's story and a manual upload's
    # story at once — both groups must get agendado, it's one publication.
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "s1", "estado": "pendiente", "aprobado": True, "story_group_id": "ai-group"},
               {"id": "s2", "estado": "pendiente", "aprobado": True, "story_group_id": "manual-group"}],
              None, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200
    updated_ids = {filters[0][1] for _, _, filters in db.updates}
    assert updated_ids == {"ai-group", "manual-group"}


def test_schedule_day_rejects_when_not_all_approved(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "s1", "estado": "pendiente", "aprobado": True, "story_group_id": "g1"},
               {"id": "s2", "estado": "pendiente", "aprobado": False, "story_group_id": "g1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 422
    assert db.updates == []


def test_schedule_day_ignores_cancelled_stories(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "s1", "estado": "pendiente", "aprobado": True, "story_group_id": "g1"},
               {"id": "s2", "estado": "cancelada", "aprobado": False, "story_group_id": "g1"}],
              None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200


def test_schedule_day_requires_stories_for_that_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 422


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


def test_drive_info_reports_image_count(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1", "drive_folder_id": "folder-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.count_images", lambda folder_id: 42 if folder_id == "folder-1" else 0)
    response = client.get("/portal/clientes/c1/drive-info")
    assert response.status_code == 200
    assert response.json() == {"count": 42}


def test_drive_info_is_null_without_a_folder(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1", "drive_folder_id": None}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes/c1/drive-info")
    assert response.status_code == 200
    assert response.json() == {"count": None}


def test_drive_info_is_null_on_drive_failure(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1", "drive_folder_id": "folder-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    def boom(folder_id): raise ValueError("no service account")
    monkeypatch.setattr("app.routers.portal.drive.count_images", boom)
    response = client.get("/portal/clientes/c1/drive-info")
    assert response.status_code == 200
    assert response.json() == {"count": None}


def test_list_clients_defaults_to_entire_agency(monkeypatch, client):
    db = DB([[{"id": "c1", "agency_id": "agency-1"}, {"id": "c2", "agency_id": "agency-1"}],
              [{"client_id": "c1"}, {"client_id": "c1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes")
    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == ["c1", "c2"]
    assert [row["stories_count"] for row in rows] == [2, 0]


def test_list_clients_can_filter_to_employee_assignments(monkeypatch, client):
    db = DB([[{"client_id": "c2"}], [{"id": "c2", "agency_id": "agency-1"}], []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes?solo_mios=true")
    assert response.status_code == 200
    assert response.json() == [{"id": "c2", "agency_id": "agency-1", "stories_count": 0}]


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
    def edit(cfg, image, text, number, font_choice=None): called.update(image=image, text=text, number=number); return "https://new"
    monkeypatch.setattr("app.routers.portal.content.editar_historia", edit)
    response = client.patch("/portal/historias/s1", json={"texto_nuevo": "updated"})
    assert response.status_code == 200
    assert called == {"image": b"original", "text": "updated", "number": 2}
    assert db.updates[-1][1] == {"text": "updated", "image_url": "https://new"}


def test_generate_story_text_analyzes_image_and_composes_result(monkeypatch, client):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_url": "https://old",
             "image_original_url": "https://original", "text": ""}
    config = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
              "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
              "calendly_link": None, "prob_link": 0}
    db = DB([story, config, [{"id": "s1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda url, timeout: SimpleNamespace(content=b"original", raise_for_status=lambda: None))
    generate_called = {}
    def generate(cfg, image): generate_called.update(image=image); return "Texto generado por la IA"
    edit_called = {}
    def edit(cfg, image, text, number, font_choice=None): edit_called.update(image=image, text=text, number=number); return "https://new"
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", generate)
    monkeypatch.setattr("app.routers.portal.content.editar_historia", edit)
    response = client.post("/portal/historias/s1/generar-texto")
    assert response.status_code == 200
    assert generate_called == {"image": b"original"}
    assert edit_called == {"image": b"original", "text": "Texto generado por la IA", "number": 1}
    assert db.updates[-1][1] == {"text": "Texto generado por la IA", "image_url": "https://new"}


def test_generate_story_text_surfaces_claude_errors(monkeypatch, client):
    from app.engine.exceptions import ClaudeGenerationError
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original"}
    config = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
              "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
              "calendly_link": None, "prob_link": 0}
    db = DB([story, config])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda url, timeout: SimpleNamespace(content=b"original", raise_for_status=lambda: None))
    def boom(cfg, image): raise ClaudeGenerationError("Claude no devolvió texto para la imagen.")
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", boom)
    response = client.post("/portal/historias/s1/generar-texto")
    assert response.status_code == 422
    assert db.updates == []


@pytest.mark.parametrize("estado", ["publicando", "publicado", "cancelada"])
def test_generate_story_text_already_published_or_cancelled_is_rejected(monkeypatch, client, estado):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original", "estado": estado}
    db = DB([story, {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda *a, **k: pytest.fail("must not re-render a locked story"))
    response = client.post("/portal/historias/s1/generar-texto")
    assert response.status_code == 409
    assert db.updates == []


def test_patch_story_font_recomposes_image_with_chosen_font(monkeypatch, client):
    story = {"id": "s1", "client_id": "c1", "order": 2, "image_url": "https://old",
             "image_original_url": "https://original", "text": "Ya tiene texto", "estado": "pendiente"}
    config = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
              "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
              "calendly_link": None, "prob_link": 0}
    db = DB([story, config, [{"id": "s1", "font_choice": "poppins", "image_url": "https://new"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda url, timeout: SimpleNamespace(content=b"original", raise_for_status=lambda: None))
    called = {}
    def edit(cfg, image, text, number, font_choice=None): called.update(image=image, text=text, number=number, font_choice=font_choice); return "https://new"
    monkeypatch.setattr("app.routers.portal.content.editar_historia", edit)
    response = client.patch("/portal/historias/s1/tipografia", json={"font_choice": "poppins"})
    assert response.status_code == 200
    assert response.json()["font_choice"] == "poppins"
    assert called == {"image": b"original", "text": "Ya tiene texto", "number": 2, "font_choice": "poppins"}
    assert db.updates[-1] == ("stories", {"font_choice": "poppins", "image_url": "https://new"}, [("id", "s1")])


def test_patch_story_font_allows_clearing_back_to_client_default(monkeypatch, client):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original", "text": "Texto"}
    config = {"id": "c1", "agency_id": "agency-1", "name": "Client", "business_description": "desc",
              "weekly_focus": None, "tone_examples": [], "topics": [], "logo_url": None,
              "calendly_link": None, "prob_link": 0}
    db = DB([story, config, [{"id": "s1", "font_choice": None}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda url, timeout: SimpleNamespace(content=b"original", raise_for_status=lambda: None))
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k: "https://new")
    response = client.patch("/portal/historias/s1/tipografia", json={"font_choice": None})
    assert response.status_code == 200
    assert db.updates == [("stories", {"font_choice": None, "image_url": "https://new"}, [("id", "s1")])]


def test_patch_story_font_rejects_unknown_key(monkeypatch, client):
    db = DB([])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/s1/tipografia", json={"font_choice": "comic-sans"})
    assert response.status_code == 422
    assert db.updates == []


def test_patch_story_font_requires_existing_text(monkeypatch, client):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original", "text": ""}
    db = DB([story, {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/historias/s1/tipografia", json={"font_choice": "poppins"})
    assert response.status_code == 422
    assert db.updates == []


@pytest.mark.parametrize("estado", ["publicando", "publicado", "cancelada"])
def test_patch_story_font_already_published_or_cancelled_is_rejected(monkeypatch, client, estado):
    story = {"id": "s1", "client_id": "c1", "order": 1, "image_original_url": "https://original",
             "text": "Texto", "estado": estado}
    db = DB([story, {"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.requests.get", lambda *a, **k: pytest.fail("must not re-render a locked story"))
    response = client.patch("/portal/historias/s1/tipografia", json={"font_choice": "poppins"})
    assert response.status_code == 409
    assert db.updates == []


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
