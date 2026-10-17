from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.deps import require_admin, require_employee
from app.main import app
from app.models.user import Employee
from app.routers import portal


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
    def upsert(self, payload, on_conflict=None): self.payload = payload; self.db.upserts.append((self.table, payload, on_conflict)); return self
    def delete(self): self.db.deletes.append((self.table, self.filters)); return self
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
        self.deletes = []
        self.upserts = []

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


@pytest.fixture
def admin():
    return Employee(id="adm-1", email="admin@example.com", name="Admin", agency_id="agency-1", role="admin")


@pytest.fixture
def admin_client(admin):
    app.dependency_overrides[require_admin] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_me_reports_current_employee(monkeypatch, client):
    response = client.get("/portal/me")
    assert response.status_code == 200
    assert response.json() == {"id": "emp-1", "name": "PM", "email": "pm@example.com",
                                "role": "employee", "agency_id": "agency-1"}



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



def test_bulk_client_entry_extracts_drive_folder_id_from_url():
    entry = portal.BulkClientEntry(
        name="X", drive_folder_id="https://drive.google.com/drive/u/0/folders/XYZ123?usp=sharing"
    )
    assert entry.drive_folder_id == "XYZ123"


def test_bulk_client_entry_keeps_bare_folder_id_untouched():
    entry = portal.BulkClientEntry(name="X", drive_folder_id="XYZ123")
    assert entry.drive_folder_id == "XYZ123"


def test_bulk_create_clients_requires_admin(client):
    response = client.post(
        "/portal/clientes/alta-masiva",
        json={"clientes": [{"name": "Nuevo", "drive_folder_id": "abc"}]},
    )
    assert response.status_code == 403


def test_bulk_create_clients_isolates_invalid_rows_and_preserves_original_row_numbers(monkeypatch, admin_client):
    db = DB([
        [{"name": "Ya Existe"}],
        [{"id": "new-1"}],
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = admin_client.post("/portal/clientes/alta-masiva", json={"clientes": [
        {"name": "Cliente Nuevo", "drive_folder_id": "https://drive.google.com/drive/folders/XYZ123?usp=sharing"},
        {"name": "Ya Existe", "drive_folder_id": "abc"},
        {"name": "cliente nuevo", "drive_folder_id": "def"},
    ]})
    assert response.status_code == 200
    resultados = response.json()["resultados"]
    assert resultados[0] == {"fila": 1, "name": "Cliente Nuevo", "status": "creado", "client_id": "new-1"}
    assert resultados[1]["fila"] == 2 and "nombre" in resultados[1]["motivo"].lower()
    assert resultados[2]["fila"] == 3 and "nombre" in resultados[2]["motivo"].lower()
    assert db.inserts == [("clients", {
        "agency_id": "agency-1", "name": "Cliente Nuevo", "drive_folder_id": "XYZ123",
        "business_description": "", "active": True,
    })]
    source = admin_client.get("/static/portal.js").text
    assert "payloadRowNumbers.push(row.fila);" in source
    assert "fila: payloadRowNumbers[i]" in source
    assert "const allResults = [...localErrors, ...serverResults].sort((a, b) => a.fila - b.fila);" in source


def test_bulk_create_clients_reports_malformed_row_without_rejecting_the_batch(monkeypatch, admin_client):
    db = DB([[], [{"id": "new-1"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = admin_client.post("/portal/clientes/alta-masiva", json={"clientes": [
        {"name": "Cliente Válido", "drive_folder_id": "abc"},
        {"name": "x" * 121, "drive_folder_id": "def"},
    ]})

    assert response.status_code == 200
    assert response.json()["resultados"] == [
        {"fila": 1, "name": "Cliente Válido", "status": "creado", "client_id": "new-1"},
        {"fila": 2, "name": "x" * 121, "status": "error",
         "motivo": "Datos inválidos: revisá nombre y carpeta de Drive."},
    ]
    assert len(db.inserts) == 1


def test_summary_reports_zero_state_with_no_clients(monkeypatch, client):
    db = DB([[]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/resumen")
    assert response.status_code == 200
    assert response.json() == {
        "historias_publicadas": 0, "historias_en_edicion": 0, "historias_agendadas": 0,
        "clientes_count": 0, "promedio_por_cliente": 0, "aprobacion_pct": None,
        "clientes_sin_actividad": [], "proximas_publicaciones": [],
    }


def test_summary_aggregates_published_and_upcoming_totals(monkeypatch, client):
    clients = [{"id": "c1", "name": "Cliente Uno"},
               {"id": "c2", "name": "Cliente Dos"},
               {"id": "c3", "name": "Cliente Tres"}]
    published = [{"id": "s1"}, {"id": "s2"}]
    upcoming = [{"client_id": "c1", "aprobado": True}, {"client_id": "c1", "aprobado": False},
                {"client_id": "c2", "aprobado": True}]
    db = DB([clients, published, upcoming])
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


def test_summary_groups_upcoming_publications_within_horizon(monkeypatch, client):
    today = date.today()
    clients = [
        {"id": "a", "name": "Álamos"},
        {"id": "b", "name": "Beta"},
        {"id": "c", "name": "Cobre"},
        {"id": "d", "name": "Delta"},
    ]
    upcoming = [
        {"client_id": "a", "aprobado": True, "fecha_publicacion": (today + timedelta(days=1)).isoformat(), "hora_publicacion": "18:30:00"},
        {"client_id": "a", "aprobado": False, "fecha_publicacion": (today + timedelta(days=1)).isoformat(), "hora_publicacion": "09:00:00"},
        {"client_id": "b", "aprobado": True, "fecha_publicacion": (today + timedelta(days=1)).isoformat(), "hora_publicacion": None},
        {"client_id": "c", "aprobado": True, "fecha_publicacion": (today + timedelta(days=2)).isoformat(), "hora_publicacion": "08:00:00"},
        {"client_id": "d", "aprobado": True, "fecha_publicacion": (today + timedelta(days=2)).isoformat(), "hora_publicacion": "08:00:00"},
        {"client_id": "b", "aprobado": True, "fecha_publicacion": (today + timedelta(days=8)).isoformat(), "hora_publicacion": "07:00:00"},
    ]
    db = DB([clients, [], upcoming])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/resumen")

    assert response.status_code == 200
    body = response.json()
    assert body["historias_agendadas"] == 5
    assert body["historias_en_edicion"] == 1
    assert body["proximas_publicaciones"] == [
        {"client_id": "a", "client_name": "Álamos", "fecha": (today + timedelta(days=1)).isoformat(),
         "hora": "09:00", "total": 2, "aprobadas": 1},
        {"client_id": "b", "client_name": "Beta", "fecha": (today + timedelta(days=1)).isoformat(),
         "hora": None, "total": 1, "aprobadas": 1},
        {"client_id": "c", "client_name": "Cobre", "fecha": (today + timedelta(days=2)).isoformat(),
         "hora": "08:00", "total": 1, "aprobadas": 1},
        {"client_id": "d", "client_name": "Delta", "fecha": (today + timedelta(days=2)).isoformat(),
         "hora": "08:00", "total": 1, "aprobadas": 1},
    ]


def test_summary_limits_upcoming_publications_to_ten_rows(monkeypatch, client):
    today = date.today().isoformat()
    clients = [{"id": f"c{index}", "name": f"Cliente {index:02d}"} for index in range(11)]
    upcoming = [
        {"client_id": client_data["id"], "aprobado": True, "fecha_publicacion": today,
         "hora_publicacion": f"{index:02d}:00:00"}
        for index, client_data in enumerate(clients)
    ]
    db = DB([clients, [], upcoming])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/resumen")

    body = response.json()
    assert body["historias_agendadas"] == 11
    assert len(body["proximas_publicaciones"]) == 10
    assert [item["client_id"] for item in body["proximas_publicaciones"]] == [f"c{index}" for index in range(10)]


def test_health_reports_empty_lists_when_agency_clients_have_no_problems(monkeypatch, client):
    db = DB([[
        {"id": "healthy", "name": "Saludable", "generation_error": None,
         "generation_error_at": None, "pool_bajo_at": None},
    ], []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/salud")

    assert response.status_code == 200
    assert response.json() == {
        "clientes_con_error_generacion": [],
        "clientes_con_pool_bajo": [],
        "clientes_con_historias_en_error": [],
    }


def test_health_aggregates_generation_pool_and_story_errors_by_agency(monkeypatch, client):
    clients = [
        {"id": "generation", "name": "Generación", "generation_error": "Claude unavailable",
         "generation_error_at": "2026-10-01T10:00:00Z", "pool_bajo_at": None},
        {"id": "pool", "name": "Pool", "generation_error": None,
         "generation_error_at": None, "pool_bajo_at": "2026-10-02T10:00:00Z"},
        {"id": "stories", "name": "Historias", "generation_error": None,
         "generation_error_at": None, "pool_bajo_at": None},
    ]
    failed_stories = [
        {"client_id": "stories", "fecha_publicacion": "2026-10-05"},
        {"client_id": "stories", "fecha_publicacion": "2026-10-03"},
    ]
    db = DB([clients, failed_stories])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/salud")

    assert response.status_code == 200
    assert response.json() == {
        "clientes_con_error_generacion": [{
            "id": "generation", "name": "Generación", "generation_error": "Claude unavailable",
            "generation_error_at": "2026-10-01T10:00:00Z",
        }],
        "clientes_con_pool_bajo": [{
            "id": "pool", "name": "Pool", "pool_bajo_at": "2026-10-02T10:00:00Z",
        }],
        "clientes_con_historias_en_error": [{
            "id": "stories", "name": "Historias", "historias_en_error": 2,
            "fecha_mas_antigua": "2026-10-03",
        }],
    }


def test_patch_client_ritmo_saves_four_distinct_days(monkeypatch, client):
    saved_days = [{"day": 1, "time": "08:00", "count": 1},
                  {"day": 3, "time": "12:00", "count": 1},
                  {"day": 5, "time": "18:00", "count": 1},
                  {"day": 6, "time": "20:00", "count": 1}]
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "c1", "publish_days": saved_days}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    unsorted = [saved_days[3], saved_days[0], saved_days[1], saved_days[2]]
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": unsorted})
    assert response.status_code == 200
    assert response.json()["publish_days"] == saved_days
    assert db.updates == [("clients", {"publish_days": saved_days}, [("id", "c1")])]


@pytest.mark.parametrize("saved_days", [
    [{"day": 2, "time": "10:00", "count": 4}],
    [{"day": 0, "time": "08:00", "count": 2},
     {"day": 4, "time": "18:00", "count": 2}],
    [{"day": 1, "time": "08:00", "count": 2},
     {"day": 3, "time": "12:00", "count": 1},
     {"day": 6, "time": "20:00", "count": 1}],
])
def test_patch_client_ritmo_saves_one_to_three_distinct_days(
        monkeypatch, client, saved_days):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "c1", "publish_days": saved_days}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": saved_days})
    assert response.status_code == 200
    assert response.json()["publish_days"] == saved_days
    assert db.updates == [("clients", {"publish_days": saved_days}, [("id", "c1")])]


def test_patch_client_ritmo_ignores_publish_together_and_requires_publish_days(
        monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_together": True})

    assert response.status_code == 400
    assert response.json() == {"detail": "Nada para actualizar"}
    assert db.updates == []


def test_patch_client_ritmo_saves_explicit_uneven_counts(monkeypatch, client):
    saved_days = [
        {"day": 0, "time": "08:00", "count": 3},
        {"day": 4, "time": "18:00", "count": 1},
    ]
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "c1", "publish_days": saved_days}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": saved_days})

    assert response.status_code == 200
    assert response.json()["publish_days"] == saved_days
    assert db.updates == [("clients", {"publish_days": saved_days}, [("id", "c1")])]


def test_patch_client_ritmo_rejects_empty_payload(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/ritmo", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "Nada para actualizar"}
    assert db.updates == []


def test_patch_client_ritmo_rejects_empty_days(client):
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": []})
    assert response.status_code == 422


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


def test_patch_client_ritmo_rejects_counts_not_summing_to_four(client):
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": [
        {"day": 1, "time": "08:00", "count": 1},
        {"day": 5, "time": "18:00", "count": 1},
    ]})
    assert response.status_code == 422


def test_patch_client_ritmo_rejects_partial_counts(client):
    response = client.patch("/portal/clientes/c1/ritmo", json={"publish_days": [
        {"day": 1, "time": "08:00", "count": 3},
        {"day": 5, "time": "18:00"},
    ]})
    assert response.status_code == 422


def test_default_ritmo_reports_global_offsets(client):
    response = client.get("/portal/ritmo-default")
    assert response.status_code == 200
    assert response.json() == {"publish_days": [
        {"day": 0, "time": "09:00", "count": 1},
        {"day": 2, "time": "09:00", "count": 1},
        {"day": 4, "time": "09:00", "count": 1},
        {"day": 6, "time": "09:00", "count": 1}]}


def test_generate_weekly_for_client_returns_created(monkeypatch, client):
    row = {"id": "c1", "agency_id": "agency-1", "publish_days": [{"day": 1, "time": "09:00"}]}
    db = DB([row])
    generated = Mock(return_value={"created": True, "group_id": "g1", "recycled": False})
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.content_jobs.local_today", lambda: date(2026, 9, 18))
    monkeypatch.setattr("app.routers.portal.content_jobs.generate_for_client", generated)

    response = client.post("/portal/clientes/c1/generar-semana")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Se generaron 4 historias para la semana que viene.",
        "created": True,
        "recycled": False,
    }
    generated.assert_called_once_with(db, row, date(2026, 9, 18))


def test_generate_weekly_for_client_reports_existing_as_normal_state(monkeypatch, client):
    row = {"id": "c1", "agency_id": "agency-1"}
    db = DB([row])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.content_jobs.generate_for_client", lambda *_: {
        "created": False, "group_id": "existing", "recycled": False,
    })

    response = client.post("/portal/clientes/c1/generar-semana")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Ya se generó contenido para esta semana.", "created": False,
    }


def test_generate_weekly_for_client_surfaces_and_persists_error(monkeypatch, client):
    row = {"id": "c1", "agency_id": "agency-1"}
    db = DB([row, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    def fail(*_):
        raise ValueError("sin imágenes suficientes: 2 disponibles; se requieren 4")

    monkeypatch.setattr("app.routers.portal.content_jobs.generate_for_client", fail)

    response = client.post("/portal/clientes/c1/generar-semana")

    assert response.status_code == 422
    assert response.json()["detail"] == "sin imágenes suficientes: 2 disponibles; se requieren 4"
    table, payload, filters = db.updates[0]
    assert table == "clients" and filters == [("id", "c1")]
    assert payload["generation_error"] == "sin imágenes suficientes: 2 disponibles; se requieren 4"
    assert payload["generation_error_at"]


def test_generate_weekly_for_client_rejects_other_agency(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-2"}])
    generated = Mock()
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.content_jobs.generate_for_client", generated)

    response = client.post("/portal/clientes/c1/generar-semana")

    assert response.status_code == 403
    generated.assert_not_called()


def test_list_font_choices_reports_all_bundled_fonts(client):
    from app.engine.imaging import _FONT_FILES, FONT_CHOICES
    response = client.get("/portal/tipografias")
    assert response.status_code == 200
    assert response.json() == [
        {"key": k, "label": v, "file": _FONT_FILES[k]} for k, v in FONT_CHOICES.items()
    ]
    assert len(response.json()) == 20


def test_list_employees_is_scoped_to_current_agency(monkeypatch, client):
    db = DB([[{"id": "emp-1", "name": "PM", "email": "pm@example.com"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/empleados")

    assert response.status_code == 200
    assert response.json() == [{"id": "emp-1", "name": "PM", "email": "pm@example.com"}]


def test_get_client_includes_assigned_employee_id(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, {"employee_id": "emp-2"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/clientes/c1")

    assert response.status_code == 200
    assert response.json()["assigned_employee_id"] == "emp-2"


def test_get_client_reports_null_when_unassigned(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/clientes/c1")

    assert response.status_code == 200
    assert response.json()["assigned_employee_id"] is None


def test_patch_client_pm_assigns_via_atomic_upsert(monkeypatch, client):
    db = DB([
        {"id": "c1", "agency_id": "agency-1"},
        {"id": "e1"},
        [{"client_id": "c1", "employee_id": "e1"}],
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/pm", json={"employee_id": "e1"})

    assert response.status_code == 200
    assert response.json() == {"client_id": "c1", "employee_id": "e1"}
    assert db.upserts == [("employee_clients", {"employee_id": "e1", "client_id": "c1"}, "client_id")]
    assert db.deletes == []


def test_patch_client_pm_rejects_employee_from_another_agency(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/pm", json={"employee_id": "foreign-emp"})

    assert response.status_code == 422
    assert db.upserts == []
    assert db.deletes == []


def test_patch_client_pm_allows_unassigning(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/pm", json={"employee_id": None})

    assert response.status_code == 200
    assert response.json() == {"client_id": "c1", "employee_id": None}
    assert db.deletes == [("employee_clients", [("client_id", "c1")])]
    assert db.upserts == []


def test_client_pm_selector_is_reset_for_each_loaded_client():
    source = TestClient(app).get("/static/portal.js").text

    assert "'client-pm'" in source
    assert "$('client-pm').value = state.client.assigned_employee_id || '';" in source
    assert "clientId !== state.client?.id" in source


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


def test_patch_client_contact_persists_only_the_supplied_contact_field(monkeypatch, client):
    db = DB([
        {"id": "c1", "agency_id": "agency-1"},
        [{"id": "c1", "instagram_profile_url": "argomedia"}],
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/contacto", json={"instagram_profile_url": "argomedia"})

    assert response.status_code == 200
    assert response.json()["instagram_profile_url"] == "argomedia"
    assert db.updates == [(
        "clients", {"instagram_profile_url": "argomedia"}, [("id", "c1")],
    )]


def test_upload_client_avatar_updates_only_avatar_and_cleans_old_asset(monkeypatch, client):
    current = {
        "id": "c1", "agency_id": "agency-1", "logo_url": "https://cdn/logo.png",
        "avatar_url": "https://cdn/old-avatar.png", "avatar_public_id": "avatar/old",
    }
    updated = {
        **current, "avatar_url": "https://cdn/new-avatar.png",
        "avatar_public_id": "avatar/new",
    }
    db = DB([current, [updated]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/new-avatar.png", public_id="avatar/new"))
    deleted = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", deleted.append)

    response = client.post("/portal/clientes/c1/avatar", files={
        "image": ("avatar.jpg", b"fake-image", "image/jpeg"),
    })

    assert response.status_code == 200
    assert response.json()["avatar_url"] == "https://cdn/new-avatar.png"
    assert db.updates == [(
        "clients", {"avatar_url": "https://cdn/new-avatar.png", "avatar_public_id": "avatar/new"},
        [("id", "c1")],
    )]
    assert "logo_url" not in db.updates[0][1]
    assert deleted == ["avatar/old"]


def test_upload_client_avatar_cleans_new_asset_when_database_update_fails(monkeypatch, client):
    class FailingUpdateQuery(Query):
        def execute(self):
            if self.table == "clients" and self.payload is not None:
                raise RuntimeError("Supabase no respondió")
            return super().execute()

    class FailingUpdateDB(DB):
        def table(self, name):
            return FailingUpdateQuery(self, name)

    db = FailingUpdateDB([{"id": "c1", "agency_id": "agency-1", "avatar_public_id": "avatar/old"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args:
                        SimpleNamespace(url="https://cdn/new-avatar.png", public_id="avatar/new"))
    deleted = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", deleted.append)

    with pytest.raises(RuntimeError, match="Supabase no respondió"):
        client.post("/portal/clientes/c1/avatar", files={
            "image": ("avatar.jpg", b"fake-image", "image/jpeg"),
        })

    assert deleted == ["avatar/new"]


def test_create_manual_story_creates_group_and_first_story(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [], [{"id": "g1"}], [{"id": "s1", "order": 1}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/img.jpg", public_id="manual/one"))
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


def test_create_manual_story_conflicts_when_the_existing_group_is_agendado(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1", "agendado": True}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    upload_calls = []
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args: upload_calls.append(args))
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-21", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 409
    assert "grupo manual agendado" in response.json()["detail"]
    assert db.inserts == []
    assert upload_calls == []


def test_create_manual_story_adds_to_existing_manual_group_on_same_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1", "agendado": False}], [{"order": 2}], [{"id": "s2", "order": 3}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/img2.jpg", public_id="manual/two"))
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})
    assert response.status_code == 200
    story_insert = next(p for t, p in db.inserts if t == "stories")
    assert story_insert["order"] == 3 and story_insert["story_group_id"] == "g1"
    assert not any(t == "story_groups" for t, _ in db.inserts)


def test_create_manual_story_returns_conflict_when_group_insert_races(monkeypatch, client):
    class ConflictQuery(Query):
        def execute(self):
            if self.table == "story_groups" and self.payload is not None:
                raise APIError({"message": "duplicate", "code": "23505", "details": None, "hint": None})
            return super().execute()

    class ConflictDB(DB):
        def table(self, name):
            return ConflictQuery(self, name)

    db = ConflictDB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    upload_calls = []
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args: upload_calls.append(args))

    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})

    assert response.status_code == 409
    assert "Ya existe un grupo manual" in response.json()["detail"]
    assert not any(table == "stories" for table, _ in db.inserts)
    assert upload_calls == []


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
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [], [{"id": "g1"}], None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    def boom(data, client_id, tag): raise uploads.UploadError("El archivo no es una imagen válida.")
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", boom)
    response = client.post("/portal/clientes/c1/historias/manual",
        data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
        files={"image": ("photo.jpg", b"not-an-image", "image/jpeg")})
    assert response.status_code == 422
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts


def test_create_manual_story_cleans_reserved_group_when_story_insert_fails(monkeypatch, client):
    class StoryFailureQuery(Query):
        def execute(self):
            if self.table == "stories" and isinstance(self.payload, dict):
                raise APIError({"message": "insert failed", "code": "XX000", "details": None, "hint": None})
            return super().execute()

    class StoryFailureDB(DB):
        def table(self, name):
            return StoryFailureQuery(self, name)

    db = StoryFailureDB([
        {"id": "c1", "agency_id": "agency-1"}, [], [{"id": "g1"}], None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args:
                        SimpleNamespace(url="https://cdn/img.jpg", public_id="manual/failed"))
    destroyed = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", destroyed.append)

    with pytest.raises(APIError):
        client.post("/portal/clientes/c1/historias/manual",
            data={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"},
            files={"image": ("photo.jpg", b"fake-bytes", "image/jpeg")})

    assert destroyed == ["manual/failed"]
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts



def test_generate_story_for_day_creates_story_from_drive_pick(monkeypatch, client):
    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [],
        {"id": "s1", "order": 1, "text": "Un texto generado", "image_url": "https://cdn/compuesta.jpg"},
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Un texto generado")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k:
                        SimpleNamespace(url="https://cdn/compuesta.jpg", public_id="edit/s1"))
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/original.jpg", public_id="ia/one"))

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 200
    assert response.json() == {"id": "s1", "order": 1, "text": "Un texto generado", "image_url": "https://cdn/compuesta.jpg"}
    reserve_call = next(payload for table, payload in db.inserts if table == "rpc:reserve_generated_story")
    assert reserve_call == {
        "p_group_id": "g1", "p_client_id": "c1", "p_agency_id": "agency-1",
        "p_fecha_publicacion": "2026-09-25", "p_hora_publicacion": "10:00:00",
    }
    finalize_call = next(payload for table, payload in db.inserts if table == "rpc:finalize_reserved_generated_story")
    assert finalize_call["p_story_id"] == "reserved-1"
    assert finalize_call["p_story"]["text"] == "Un texto generado"
    assert finalize_call["p_story"]["image_url"] == "https://cdn/compuesta.jpg"
    assert finalize_call["p_story"]["image_original_url"] == "https://cdn/original.jpg"
    assert finalize_call["p_image"] == {"drive_file_id": "f1", "drive_file_name": "foto.jpg"}


def test_generate_story_for_day_rejects_when_drive_pool_is_empty(monkeypatch, client):
    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [], None, None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [])

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 422
    assert "no tiene imágenes disponibles" in response.json()["detail"]
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts


def test_generate_story_for_day_surfaces_claude_errors(monkeypatch, client):
    from app.engine.exceptions import ClaudeGenerationError
    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [], None, None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    def boom(config, image_bytes):
        raise ClaudeGenerationError("Claude no pudo generar el texto.")
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", boom)

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Claude no pudo generar el texto."
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts


def test_generate_story_for_day_releases_reservation_on_image_composition_error(monkeypatch, client):
    from app.engine.exceptions import ImageProcessingError

    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [], None, None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Texto")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *args, **kwargs:
                        (_ for _ in ()).throw(ImageProcessingError("No se pudo componer")))

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 422
    assert response.json()["detail"] == "No se pudo componer"
    assert ("rpc:release_reserved_generated_story", {"p_story_id": "reserved-1"}) in db.inserts
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts


def test_generate_story_for_day_reserves_before_spending_generation_resources(monkeypatch, client):
    events = []

    class OrderedDB(DB):
        def rpc(self, name, payload):
            events.append(name)
            return super().rpc(name, payload)

    db = OrderedDB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [{"id": "g1", "agendado": False}], {"id": "reserved-4", "order": 4}, [],
        {"id": "s4", "order": 4},
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes:
                        events.append("generate_text") or "Texto")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *args, **kwargs:
                        events.append(("compose", args[3])) or SimpleNamespace(url="https://cdn/edited.jpg", public_id="edit/s4"))
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args:
                        events.append("upload_original") or SimpleNamespace(url="https://cdn/original.jpg", public_id="ia/s4"))

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 200
    assert events == [
        "reserve_generated_story", "generate_text", ("compose", 4),
        "upload_original", "finalize_reserved_generated_story",
    ]


def test_generate_story_for_day_cleans_up_composed_image_when_original_upload_fails(monkeypatch, client):
    from app.services import uploads

    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [], None, None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Un texto generado")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k:
                        SimpleNamespace(url="https://cdn/compuesta.jpg", public_id="edit/orphan"))
    def boom(data, client_id, tag):
        raise uploads.UploadError("Cloudinary no respondió.")
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", boom)
    destroyed = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", destroyed.append)

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 422
    assert destroyed == ["edit/orphan"]
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts
    assert ("rpc:release_reserved_generated_story", {"p_story_id": "reserved-1"}) in db.inserts
    assert not any(table == "rpc:finalize_reserved_generated_story" for table, _ in db.inserts)


def test_generate_story_for_day_cleans_up_both_assets_when_group_is_scheduled_during_generation(monkeypatch, client):
    class RpcFailureQuery(Query):
        def execute(self):
            if self.table == "rpc:finalize_reserved_generated_story":
                raise APIError({"message": "Reserved story group is no longer available", "code": "P0001", "details": None, "hint": None})
            return super().execute()

    class RpcFailureDB(DB):
        def table(self, name):
            return RpcFailureQuery(self, name)

        def rpc(self, name, payload):
            self.inserts.append((f"rpc:{name}", payload))
            return RpcFailureQuery(self, f"rpc:{name}")

    db = RpcFailureDB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [], [{"id": "g1"}], {"id": "reserved-1", "order": 1}, [],
        {"id": "reserved-1", "estado": "generando", "image_url": None, "image_original_url": None},
        None, None,
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Un texto generado")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k:
                        SimpleNamespace(url="https://cdn/compuesta.jpg", public_id="edit/orphan"))
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/original.jpg", public_id="ia/orphan"))
    destroyed = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", destroyed.append)

    with pytest.raises(APIError):
        client.post("/portal/clientes/c1/historias/generar",
            json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert set(destroyed) == {"ia/orphan", "edit/orphan"}
    assert ("rpc:delete_empty_manual_group", {"p_group_id": "g1"}) in db.inserts


def test_generate_story_for_day_keeps_assets_when_finalize_transport_fails_after_commit(monkeypatch, client):
    class TransportFailureQuery(Query):
        def execute(self):
            if self.table == "rpc:finalize_reserved_generated_story":
                raise APIError({"message": "connection reset", "code": "08006", "details": None, "hint": None})
            return super().execute()

    class TransportFailureDB(DB):
        def rpc(self, name, payload):
            self.inserts.append((f"rpc:{name}", payload))
            return TransportFailureQuery(self, f"rpc:{name}")

    db = TransportFailureDB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [{"id": "g1", "agendado": False}], {"id": "reserved-1", "order": 1}, [],
        {"id": "reserved-1", "estado": "pendiente", "image_url": "https://cdn/compuesta.jpg",
         "image_original_url": "https://cdn/original.jpg"},
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Texto")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *args, **kwargs:
                        SimpleNamespace(url="https://cdn/compuesta.jpg", public_id="edit/kept"))
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda *args:
                        SimpleNamespace(url="https://cdn/original.jpg", public_id="ia/kept"))
    destroyed = []
    monkeypatch.setattr("app.routers.portal.uploads.delete_image", destroyed.append)

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 200
    assert response.json()["id"] == "reserved-1"
    assert destroyed == []
    assert not any(table == "rpc:release_reserved_generated_story" for table, _ in db.inserts)


def test_generate_story_for_day_adds_to_existing_manual_group(monkeypatch, client):
    db = DB([
        {"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"},
        [{"id": "g1", "agendado": False}], {"id": "reserved-3", "order": 3},
        [{"drive_file_id": "f1", "last_used_at": "2026-01-01T00:00:00Z"}],
        {"id": "s2", "order": 3},
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.drive.list_image_metadata", lambda folder_id: [("f1", "foto.jpg")])
    monkeypatch.setattr("app.routers.portal.drive.download_images", lambda images, limit=None: [("f1", "foto.jpg", b"bytes")])
    monkeypatch.setattr("app.routers.portal.content.generar_texto_para_imagen", lambda config, image_bytes: "Otro texto")
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k:
                        SimpleNamespace(url="https://cdn/compuesta2.jpg", public_id="edit/s2"))
    monkeypatch.setattr("app.routers.portal.uploads.upload_image", lambda data, client_id, tag:
                        SimpleNamespace(url="https://cdn/original2.jpg", public_id="ia/two"))

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "2026-09-25", "hora_publicacion": "10:00"})

    assert response.status_code == 200
    reserve_call = next(payload for table, payload in db.inserts if table == "rpc:reserve_generated_story")
    assert reserve_call["p_group_id"] == "g1"
    finalize_call = next(payload for table, payload in db.inserts if table == "rpc:finalize_reserved_generated_story")
    assert finalize_call["p_story"]["text"] == "Otro texto"
    assert not any(table == "story_groups" for table, _ in db.inserts)
    assert not any(entry[0] == "client_images" for entry in db.updates)


def test_generate_story_for_day_rejects_invalid_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1", "name": "Cliente Test", "drive_folder_id": "folder-1"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.post("/portal/clientes/c1/historias/generar",
        json={"fecha_publicacion": "no-es-una-fecha", "hora_publicacion": "10:00"})

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
              [{"id": "s1", "estado": "pendiente"}, {"id": "s2", "estado": "publicado"}],  # stories lookup
              None,                                                 # stories update
              None])                                                # story_groups update
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
    assert [update[0] for update in db.updates] == ["stories", "story_groups"]


def test_update_manual_day_time_preserves_already_scheduled_story(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, [{"id": "g1"}],
             [{"id": "editable", "estado": "pendiente", "agendado": False},
              {"id": "scheduled", "estado": "pendiente", "agendado": True}],
             None, None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/historias/manual/2026-09-25/hora",
                            json={"hora_publicacion": "14:30"})

    assert response.status_code == 200
    assert db.updates[0] == (
        "stories", {"hora_publicacion": "14:30:00"}, [("id", ["editable"])]
    )


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


def test_update_generated_day_time_updates_only_editable_stories_on_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "s1", "estado": "pendiente", "agendado": False,
               "story_group_id": "ai-week"},
              {"id": "s2", "estado": "publicado", "agendado": True,
               "story_group_id": "old-week"}],
             None,
             None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-28/hora",
                            json={"hora_publicacion": "11:45"})

    assert response.status_code == 200
    assert response.json() == {"detail": "Hora actualizada", "updated": 1}
    assert db.updates == [
        ("stories", {"hora_publicacion": "11:45:00"}, [("id", ["s1"])]),
        ("story_groups", {"scheduled_time": "11:45:00"},
         [("id", ["ai-week"]), ("scheduled_date", "2026-09-28")]),
    ]


def test_update_generated_day_time_preserves_confirmed_story_on_same_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "pending", "estado": "pendiente", "agendado": False,
               "story_group_id": "ai-week"},
              {"id": "confirmed", "estado": "pendiente", "agendado": True,
               "story_group_id": "ai-week"}],
             None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-28/hora",
                            json={"hora_publicacion": "11:45"})

    assert response.status_code == 200
    assert response.json() == {"detail": "Hora actualizada", "updated": 1}
    assert db.updates == [
        ("stories", {"hora_publicacion": "11:45:00"}, [("id", ["pending"])]),
    ]


def test_update_generated_day_time_requires_client_in_employee_agency(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "another-agency"}])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-28/hora",
                            json={"hora_publicacion": "11:45"})

    assert response.status_code == 403
    assert db.updates == []


def test_update_generated_day_time_rejects_locked_stories(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "s1", "estado": "publicando", "story_group_id": "ai-week"},
              {"id": "s2", "estado": "publicado", "story_group_id": "ai-week"}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-28/hora",
                            json={"hora_publicacion": "11:45"})

    assert response.status_code == 409
    assert db.updates == []


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
              None,
              [{"id": "s1", "estado": "pendiente", "agendado": True},
               {"id": "s2", "estado": "pendiente", "agendado": True}],
              None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200
    assert response.json() == {"detail": "Publicación agendada"}
    assert db.updates == [
        ("stories", {"agendado": True}, [("id", ["s1", "s2"])]),
        ("story_groups", {"agendado": True}, [("id", "g1")]),
    ]


def test_schedule_day_keeps_other_dates_in_weekly_group_actionable(monkeypatch, client):
    """Confirming Monday must not complete a Mon/Wed/Fri/Sun AI group."""
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "mon", "estado": "pendiente", "aprobado": True,
                "story_group_id": "weekly"}],
              None,
              [{"id": "mon", "estado": "pendiente", "agendado": True},
               {"id": "wed", "estado": "pendiente", "agendado": False},
               {"id": "fri", "estado": "pendiente", "agendado": False},
               {"id": "sun", "estado": "pendiente", "agendado": False}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-21/agendar")

    assert response.status_code == 200
    assert db.updates == [("stories", {"agendado": True}, [("id", ["mon"])])]


def test_schedule_day_marks_weekly_group_complete_on_final_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "sun", "estado": "pendiente", "aprobado": True,
                "story_group_id": "weekly"}],
              None,
              [{"id": "mon", "estado": "pendiente", "agendado": True},
               {"id": "wed", "estado": "pendiente", "agendado": True},
               {"id": "fri", "estado": "pendiente", "agendado": True},
               {"id": "sun", "estado": "pendiente", "agendado": True}],
              None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.patch("/portal/clientes/c1/dias/2026-09-27/agendar")

    assert response.status_code == 200
    assert db.updates[-1] == ("story_groups", {"agendado": True}, [("id", "weekly")])


def test_schedule_day_bundles_every_group_sharing_that_date(monkeypatch, client):
    # A day can be published from an AI batch's story and a manual upload's
    # story at once — both groups must get agendado, it's one publication.
    db = DB([{"id": "c1", "agency_id": "agency-1"},
              [{"id": "s1", "estado": "pendiente", "aprobado": True, "story_group_id": "ai-group"},
               {"id": "s2", "estado": "pendiente", "aprobado": True, "story_group_id": "manual-group"}],
              None,
              [{"id": "s1", "estado": "pendiente", "agendado": True}], None,
              [{"id": "s2", "estado": "pendiente", "agendado": True}], None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200
    updated_ids = {filters[0][1] for table, _, filters in db.updates if table == "story_groups"}
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
              None,
              [{"id": "s1", "estado": "pendiente", "agendado": True},
               {"id": "s2", "estado": "cancelada", "agendado": False}],
              None])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 200


def test_schedule_day_requires_stories_for_that_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.patch("/portal/clientes/c1/dias/2026-09-25/agendar")
    assert response.status_code == 422


def test_publish_day_now_succeeds_when_all_approved(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "s1", "estado": "pendiente", "aprobado": True}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    monkeypatch.setattr("app.routers.portal.content_jobs.publish_now",
                        lambda db, client_id, fecha: {"publicadas": 1, "fallidas": 0})

    response = client.post("/portal/clientes/c1/dias/2026-09-25/publicar-ahora")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Publicación enviada a Instagram", "publicadas": 1, "fallidas": 0,
    }


def test_publish_day_now_rejects_when_not_all_approved(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"},
             [{"id": "s1", "estado": "pendiente", "aprobado": True},
              {"id": "s2", "estado": "pendiente", "aprobado": False}]])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.post("/portal/clientes/c1/dias/2026-09-25/publicar-ahora")

    assert response.status_code == 422


def test_publish_day_now_requires_stories_for_that_date(monkeypatch, client):
    db = DB([{"id": "c1", "agency_id": "agency-1"}, []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.post("/portal/clientes/c1/dias/2026-09-25/publicar-ahora")

    assert response.status_code == 422



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
    assert [row["pending_count"] for row in rows] == [2, 0]


def test_list_clients_reports_pending_count_for_upcoming_stories(monkeypatch, client):
    db = DB([
        [{"id": "c1", "agency_id": "agency-1"}, {"id": "c2", "agency_id": "agency-1"}],
        [
            {"client_id": "c1", "aprobado": True, "estado": "pendiente"},
            {"client_id": "c1", "aprobado": False, "estado": "pendiente"},
        ],
    ])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/clientes")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "c1", "agency_id": "agency-1", "stories_count": 2, "pending_count": 1},
        {"id": "c2", "agency_id": "agency-1", "stories_count": 0, "pending_count": 0},
    ]


def test_list_clients_can_filter_to_employee_assignments(monkeypatch, client):
    db = DB([[{"client_id": "c2"}], [{"id": "c2", "agency_id": "agency-1"}], []])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)
    response = client.get("/portal/clientes?solo_mios=true")
    assert response.status_code == 200
    assert response.json() == [{"id": "c2", "agency_id": "agency-1", "stories_count": 0, "pending_count": 0}]


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


def test_list_stories_hides_transient_generation_reservations(monkeypatch, client):
    groups = [{"id": "g1", "stories": [
        {"id": "reserved", "estado": "generando"},
        {"id": "ready", "estado": "pendiente"},
    ]}]
    db = DB([{"id": "c1", "agency_id": "agency-1"}, groups])
    monkeypatch.setattr("app.routers.portal.get_admin_client", lambda: db)

    response = client.get("/portal/clientes/c1/historias")

    assert response.status_code == 200
    assert [story["id"] for story in response.json()[0]["stories"]] == ["ready"]


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
    def edit(cfg, image, text, number, font_choice=None):
        called.update(image=image, text=text, number=number)
        return SimpleNamespace(url="https://new", public_id="edit/s1")
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
    def edit(cfg, image, text, number, font_choice=None):
        edit_called.update(image=image, text=text, number=number)
        return SimpleNamespace(url="https://new", public_id="edit/s1")
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
    def edit(cfg, image, text, number, font_choice=None):
        called.update(image=image, text=text, number=number, font_choice=font_choice)
        return SimpleNamespace(url="https://new", public_id="edit/s1")
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
    monkeypatch.setattr("app.routers.portal.content.editar_historia", lambda *a, **k:
                        SimpleNamespace(url="https://new", public_id="edit/s1"))
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
