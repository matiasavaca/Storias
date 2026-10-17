from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.engine.exceptions import ClaudeGenerationError, MetaPublishError
from app.engine.schemas import HiloGenerado, ResultadoPublicacion
from app.services import content_jobs as jobs


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters = db, name, []
        self.in_filters = []
        self.op = None
        self.values = None
        self.sort = []
        self.bounds = None
        self.or_expr = None

    def select(self, *_): return self
    def eq(self, key, value):
        self.filters.append((key, value))
        return self
    def in_(self, key, values):
        self.in_filters.append((key, values))
        return self
    def or_(self, expr):
        self.or_expr = expr
        return self
    def order(self, key):
        self.sort.append(key)
        return self
    def update(self, values):
        self.op = "update"
        self.values = values
        return self
    def delete(self):
        self.op = "delete"
        return self
    def range(self, start, end):
        self.bounds = (start, end)
        return self
    def _matches_or(self, row):
        if not self.or_expr:
            return True
        for clause in self.or_expr.split(','):
            field, op, value = clause.split('.', 2)
            cell = row.get(field)
            if op == 'is' and value == 'null' and cell is None:
                return True
            if op == 'lte' and cell is not None and str(cell) <= value:
                return True
        return False
    def execute(self):
        rows = [r for r in self.db.rows[self.name]
                if all(r.get(k) == v for k, v in self.filters)
                and all(r.get(k) in values for k, values in self.in_filters)
                and self._matches_or(r)]
        for key in reversed(self.sort):
            rows.sort(key=lambda r: r[key])
        if self.bounds:
            rows = rows[self.bounds[0]:self.bounds[1] + 1]
        if self.op == "delete":
            deleted_ids = {id(row) for row in rows}
            self.db.rows[self.name] = [
                row for row in self.db.rows[self.name] if id(row) not in deleted_ids
            ]
            if self.name == "story_groups":
                deleted_group_ids = {row.get("id") for row in rows}
                self.db.rows["stories"] = [
                    story for story in self.db.rows["stories"]
                    if story.get("story_group_id") not in deleted_group_ids
                ]
        elif self.op == "update":
            for row in rows: row.update(self.values)
        return SimpleNamespace(data=deepcopy(rows))


class Database:
    def __init__(self, clients=(), stories=()):
        self.rows = {"clients": list(clients), "stories": list(stories), "story_groups": [],
                     "client_images": []}
        self.saved = []

    def table(self, name): return Query(self, name)
    def rpc(self, name, payload):
        assert name == "persist_generated_thread"
        self.saved.append(payload)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data="group-id"))


def client(id="good", **overrides):
    base = dict(id=id, agency_id="agency", name="Studio", active=True,
                business_description="Helpful studio", tone_examples=[["a", "b", "c", "d"]],
                topics=["design"], weekly_focus="Launch", weekly_focus_expires_at="2026-09-20",
                drive_folder_id=id, logo_url="logo", calendly_link="booking", prob_link=1)
    base.update(overrides)
    return base


def images(n=5): return [(f"file-{i}", f"image-{i}.jpg", b"image") for i in range(n)]


def image_metadata(n=5): return [(f"file-{i}", f"image-{i}.jpg") for i in range(n)]


def generated(cta_agregado=True):
    return HiloGenerado(historias=[f"Story {i}" for i in range(4)],
        imagenes_originales_url=[f"raw-{i}" for i in range(4)],
        imagenes_editadas_url=[f"edited-{i}" for i in range(4)],
        drive_file_ids_usados=[f"file-{i}" for i in range(4)],
        cta_agregado=cta_agregado)


@pytest.fixture
def generation(monkeypatch):
    drive = Mock(return_value=image_metadata())
    download = Mock(side_effect=lambda rows, limit: [(*row, b"image") for row in rows[:limit]])
    engine = Mock(return_value=generated())
    monkeypatch.setattr(jobs.drive, "list_image_metadata", drive)
    monkeypatch.setattr(jobs.drive, "download_images", download)
    monkeypatch.setattr(jobs.content, "generar_hilo", engine)
    return drive, engine


def test_build_content_config_defaults_null_business_description_and_tone_examples():
    row = client(business_description=None, tone_examples=None, prob_link=None)
    config = jobs.build_content_config(row)
    assert config.business_description == "" and config.tone_examples == [] and config.prob_link == 0.0


def test_generate_for_client_returns_existing_group_without_external_work(generation):
    drive, engine = generation
    db = Database([client()])
    db.rows["story_groups"].append({
        "id": "existing-group", "client_id": "good", "generation_week": "2026-09-14",
    })

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result == {"created": False, "group_id": "existing-group", "recycled": False}
    drive.assert_not_called()
    engine.assert_not_called()
    assert db.saved == []


def test_generate_for_client_blocks_when_existing_batch_still_has_active_stories(generation):
    drive, engine = generation
    db = Database([client()])
    db.rows["story_groups"].append({
        "id": "existing-group", "client_id": "good", "generation_week": "2026-09-14",
    })
    db.rows["stories"].extend([
        {"id": "s1", "story_group_id": "existing-group", "estado": "cancelada"},
        {"id": "s2", "story_group_id": "existing-group", "estado": "pendiente"},
    ])

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result == {"created": False, "group_id": "existing-group", "recycled": False}
    drive.assert_not_called()
    engine.assert_not_called()
    assert any(group["id"] == "existing-group" for group in db.rows["story_groups"])


def test_generate_for_client_regenerates_when_existing_batch_is_fully_cancelled(generation):
    db = Database([client()])
    db.rows["story_groups"].append({
        "id": "existing-group", "client_id": "good", "generation_week": "2026-09-14",
    })
    db.rows["stories"].extend([
        {"id": "s1", "story_group_id": "existing-group", "estado": "cancelada"},
        {"id": "s2", "story_group_id": "existing-group", "estado": "cancelada"},
    ])

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result == {"created": True, "group_id": "group-id", "recycled": False}
    assert not any(group["id"] == "existing-group" for group in db.rows["story_groups"])
    assert not any(story["story_group_id"] == "existing-group" for story in db.rows["stories"])
    assert len(db.saved) == 1


def test_generate_for_client_persists_and_reports_success(generation):
    db = Database([client()])

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result == {"created": True, "group_id": "group-id", "recycled": False}
    assert len(db.saved) == 1
    assert db.saved[0]["p_client_id"] == "good"


def test_generate_for_client_clears_pool_bajo_after_a_generation_without_recycling(generation):
    db = Database([client(pool_bajo_at="2026-09-10T00:00:00+00:00")])

    jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert db.rows["clients"][0]["pool_bajo_at"] is None


def test_generate_for_client_marks_pool_bajo_after_recycling(generation):
    _, engine = generation
    db = Database([client()])
    now = datetime.now(timezone.utc)
    db.rows["client_images"] = [
        {"client_id": "good", "drive_file_id": f"file-{index}",
         "last_used_at": (now - timedelta(days=1)).isoformat()}
        for index in range(3)
    ]
    engine.return_value = HiloGenerado(
        historias=[f"Story {index}" for index in range(4)],
        imagenes_originales_url=[f"raw-{index}" for index in range(4)],
        imagenes_editadas_url=[f"edited-{index}" for index in range(4)],
        drive_file_ids_usados=["file-3", "file-4", "file-0", "file-1"],
    )

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result["recycled"] is True
    assert db.rows["clients"][0]["pool_bajo_at"] is not None


def test_generate_for_client_keeps_success_when_pool_bookkeeping_fails(generation):
    class PoolBookkeepingFailureDatabase(Database):
        def table(self, name):
            if name != "clients":
                return super().table(name)

            class FailingQuery(Query):
                def execute(self):
                    if self.op == "update" and self.values and "pool_bajo_at" in self.values:
                        raise RuntimeError("pool flag unavailable")
                    return super().execute()

            return FailingQuery(self, name)

    db = PoolBookkeepingFailureDatabase([client()])

    result = jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert result == {"created": True, "group_id": "group-id", "recycled": False}
    assert len(db.saved) == 1


def test_generate_for_client_propagates_operational_errors(generation):
    drive, _ = generation
    drive.side_effect = RuntimeError("Drive unavailable")
    db = Database([client()])

    with pytest.raises(RuntimeError, match="Drive unavailable"):
        jobs.generate_for_client(db, db.rows["clients"][0], date(2026, 9, 18))

    assert db.saved == []
    assert "generation_error" not in db.rows["clients"][0]


def test_generate_for_client_by_id_fetches_fresh_row_and_generates(generation):
    db = Database([client()])

    jobs.generate_for_client_by_id(db, "good", date(2026, 9, 18))

    assert len(db.saved) == 1


def test_generate_for_client_by_id_skips_inactive_or_missing_client(generation):
    db = Database([client(active=False)])

    jobs.generate_for_client_by_id(db, "good", date(2026, 9, 18))

    assert db.saved == []
    jobs.generate_for_client_by_id(Database([]), "nope", date(2026, 9, 18))


def test_weekly_does_not_crash_for_client_with_no_business_description_yet(generation):
    _, engine = generation
    db = Database([client("onboarding", business_description=None, tone_examples=None), client()])
    jobs.generate_weekly(db, date(2026, 9, 18))
    assert "generation_error" not in db.rows["clients"][0]
    assert {p["p_client_id"] for p in db.saved} == {"onboarding", "good"}


def test_weekly_continues_after_insufficient_images_and_saves_complete_thread(generation):
    drive, engine = generation
    drive.side_effect = lambda folder: image_metadata(2 if folder == "a-short" else 5)
    db = Database([client("a-short"), client()])
    jobs.generate_weekly(db, date(2026, 9, 18))
    assert "sin imágenes suficientes" in db.rows["clients"][0]["generation_error"]
    assert db.rows["clients"][0]["weekly_focus"] == "Launch"
    assert len(db.saved) == 1
    config, selected = engine.call_args.args
    assert config.client_id == "good" and config.nombre_negocio == "Studio"
    assert config.topics == ["design"] and config.tone_examples == [["a", "b", "c", "d"]]
    assert [image.drive_file_id for image in selected] == [f"file-{i}" for i in range(4)]
    saved = db.saved[0]
    assert saved["p_used_focus"] == "Launch"
    assert saved["p_used_focus_expires_at"] == "2026-09-20"
    assert saved["p_generation_week"] == "2026-09-14"
    assert saved["p_scheduled_date"] == "2026-09-21"
    assert len(saved["p_stories"]) == 4 and len(saved["p_images"]) == 4
    assert saved["p_stories"][0]["image_original_url"] == "raw-0"
    assert saved["p_stories"][0]["image_url"] == "edited-0"
    assert saved["p_stories"][3]["agregar_cta"] is True
    assert saved["p_images"][0] == {"drive_file_id": "file-0", "drive_file_name": "image-0.jpg"}
    # Spread across the week (Mon/Wed/Fri/Sun) instead of all four sharing p_scheduled_date.
    assert [s["fecha_publicacion"] for s in saved["p_stories"]] == [
        "2026-09-21", "2026-09-23", "2026-09-25", "2026-09-27"]


def test_weekly_uses_clients_custom_publish_schedule(generation):
    _, engine = generation
    custom = [{"day": 1, "time": "08:00"}, {"day": 3, "time": "12:30"},
              {"day": 5, "time": "18:00"}, {"day": 6, "time": "20:15"}]  # Tue/Thu/Sat/Sun
    db = Database([client(publish_days=custom)])
    jobs.generate_weekly(db, date(2026, 9, 18))
    stories = db.saved[0]["p_stories"]
    assert [s["fecha_publicacion"] for s in stories] == [
        "2026-09-22", "2026-09-24", "2026-09-26", "2026-09-27"]
    assert [s["hora_publicacion"] for s in stories] == [
        "08:00:00", "12:30:00", "18:00:00", "20:15:00"]


def test_weekly_publish_together_uses_first_ordered_slot_for_all_four_stories(generation):
    custom = [{"day": 5, "time": "18:00"}, {"day": 1, "time": "08:30"}]
    db = Database([client(publish_days=custom, publish_together=True)])

    jobs.generate_weekly(db, date(2026, 9, 18))

    stories = db.saved[0]["p_stories"]
    assert [story["fecha_publicacion"] for story in stories] == ["2026-09-22"] * 4
    assert [story["hora_publicacion"] for story in stories] == ["08:30:00"] * 4


def test_weekly_uses_explicit_uneven_story_counts(generation):
    custom = [
        {"day": 0, "time": "08:00", "count": 3},
        {"day": 4, "time": "18:00", "count": 1},
    ]
    # An old true flag may remain after the new UI saves explicit counts;
    # explicit counts must take precedence over the legacy fallback.
    db = Database([client(publish_days=custom, publish_together=True)])

    jobs.generate_weekly(db, date(2026, 9, 18))

    stories = db.saved[0]["p_stories"]
    assert [story["fecha_publicacion"] for story in stories] == [
        "2026-09-21", "2026-09-21", "2026-09-21", "2026-09-25"]
    assert [story["hora_publicacion"] for story in stories] == [
        "08:00:00", "08:00:00", "08:00:00", "18:00:00"]


def test_weekly_single_explicit_day_replaces_publish_together(generation):
    db = Database([client(publish_days=[{"day": 2, "time": "10:15", "count": 4}])])

    jobs.generate_weekly(db, date(2026, 9, 18))

    stories = db.saved[0]["p_stories"]
    assert [story["fecha_publicacion"] for story in stories] == ["2026-09-23"] * 4
    assert [story["hora_publicacion"] for story in stories] == ["10:15:00"] * 4


@pytest.mark.parametrize("publish_together", [False, None])
def test_weekly_publish_together_disabled_or_missing_preserves_distribution(
        generation, publish_together):
    custom = [{"day": 1, "time": "08:00"}, {"day": 5, "time": "18:00"}]
    overrides = {"publish_days": custom}
    if publish_together is not None:
        overrides["publish_together"] = publish_together
    db = Database([client(**overrides)])

    jobs.generate_weekly(db, date(2026, 9, 18))

    stories = db.saved[0]["p_stories"]
    assert [story["fecha_publicacion"] for story in stories] == [
        "2026-09-22", "2026-09-22", "2026-09-26", "2026-09-26"]
    assert [story["hora_publicacion"] for story in stories] == [
        "08:00:00", "08:00:00", "18:00:00", "18:00:00"]


@pytest.mark.parametrize("custom,expected_dates,expected_times", [
    ([{"day": 2, "time": "10:00"}],
     ["2026-09-23"] * 4, ["10:00:00"] * 4),
    ([{"day": 0, "time": "08:00"}, {"day": 4, "time": "18:00"}],
     ["2026-09-21", "2026-09-21", "2026-09-25", "2026-09-25"],
     ["08:00:00", "08:00:00", "18:00:00", "18:00:00"]),
    ([{"day": 1, "time": "08:00"}, {"day": 3, "time": "12:00"},
      {"day": 6, "time": "20:00"}],
     ["2026-09-22", "2026-09-22", "2026-09-24", "2026-09-27"],
     ["08:00:00", "08:00:00", "12:00:00", "20:00:00"]),
])
def test_weekly_balances_four_stories_across_one_to_three_days(
        generation, custom, expected_dates, expected_times):
    db = Database([client(publish_days=custom)])
    jobs.generate_weekly(db, date(2026, 9, 18))
    stories = db.saved[0]["p_stories"]
    assert [story["fecha_publicacion"] for story in stories] == expected_dates
    assert [story["hora_publicacion"] for story in stories] == expected_times


_GLOBAL_SCHEDULE = tuple((offset, "09:00", 1) for offset in jobs.PUBLISH_DAY_OFFSETS)


@pytest.mark.parametrize("days,expected", [
    (None, _GLOBAL_SCHEDULE),
    ([{"day":0,"time":"08:00"},{"day":2,"time":"08:00"},{"day":4,"time":"08:00"},{"day":6,"time":"08:00"}],
     ((0,"08:00",1),(2,"08:00",1),(4,"08:00",1),(6,"08:00",1))),
    ([{"day":6,"time":"08:00"},{"day":0,"time":"08:00"},{"day":2,"time":"08:00"},{"day":4,"time":"08:00"}],
     ((0,"08:00",1),(2,"08:00",1),(4,"08:00",1),(6,"08:00",1))),  # sorted by day
    ([{"day":5,"time":"18:00"},{"day":1,"time":"08:00"}],
     ((1,"08:00",2),(5,"18:00",2))),
    ([{"day":3,"time":"12:30"}], ((3,"12:30",4),)),
    ([{"day":0,"time":"08:00","count":3},{"day":4,"time":"18:00","count":1}],
     ((0,"08:00",3),(4,"18:00",1))),
    ([{"day":0,"time":"08:00","count":1},{"day":4,"time":"18:00","count":1}],
     ((0,"08:00",2),(4,"18:00",2))),  # invalid total -> legacy split
    ([{"day":0,"time":"08:00","count":3},{"day":4,"time":"18:00"}],
     ((0,"08:00",2),(4,"18:00",2))),  # partial counts -> legacy split
    ([], _GLOBAL_SCHEDULE),
    ([{"day":0,"time":"08:00"},{"day":0,"time":"09:00"},{"day":2,"time":"08:00"},{"day":4,"time":"08:00"}],
     _GLOBAL_SCHEDULE),  # not 4 distinct days -> fall back
    ([{"day":0,"time":"08:00"},{"day":2,"time":"08:00"},{"day":4,"time":"08:00"},{"day":7,"time":"08:00"}],
     _GLOBAL_SCHEDULE),  # out of range -> fall back
    ([{"day":0,"time":"25:00"},{"day":2,"time":"08:00"},{"day":4,"time":"08:00"},{"day":6,"time":"08:00"}],
     _GLOBAL_SCHEDULE),  # invalid time -> fall back
    ("garbage", _GLOBAL_SCHEDULE),
])
def test_publish_schedule_validates_and_falls_back(days, expected):
    assert jobs.publish_schedule({"publish_days": days}) == tuple(expected)


def test_engine_error_does_not_stop_next_client_or_consume_focus(generation):
    _, engine = generation
    engine.side_effect = [ClaudeGenerationError("Claude unavailable"), generated()]
    db = Database([client("broken"), client()])
    jobs.generate_weekly(db, date(2026, 9, 18))
    assert db.rows["clients"][0]["generation_error"] == "Claude unavailable"
    assert db.rows["clients"][0]["weekly_focus"] == "Launch"
    assert [p["p_client_id"] for p in db.saved] == ["good"]


def test_history_read_failure_is_logged_marks_error_and_skips_only_that_client(
        generation, caplog):
    drive, engine = generation

    class HistoryFailureQuery(Query):
        def execute(self):
            if ("client_id", "broken") in self.filters:
                raise RuntimeError("Supabase history unavailable")
            return super().execute()

    class HistoryFailureDatabase(Database):
        def table(self, name):
            if name == "client_images":
                return HistoryFailureQuery(self, name)
            return super().table(name)

    db = HistoryFailureDatabase([client("broken"), client()])
    with caplog.at_level("ERROR"):
        jobs.generate_weekly(db, date(2026, 9, 18))

    assert "No se pudo leer el historial" in db.rows["clients"][0]["generation_error"]
    assert "Could not read image history for client broken" in caplog.text
    assert [p["p_client_id"] for p in db.saved] == ["good"]
    assert engine.call_count == 1
    assert drive.call_count == 2


def test_inactive_and_already_generated_clients_skip_engine(generation):
    drive, engine = generation
    disabled = client("disabled")
    disabled["active"] = False
    db = Database([disabled, client()])
    db.rows["story_groups"].append({"client_id": "good", "generation_week": "2026-09-14"})
    jobs.generate_weekly(db, date(2026, 9, 18))
    drive.assert_not_called()
    engine.assert_not_called()


def test_invalid_engine_result_is_not_partially_saved(generation):
    _, engine = generation
    result = generated()
    result.historias.pop()
    engine.return_value = result
    db = Database([client()])
    jobs.generate_weekly(db, date(2026, 9, 18))
    assert db.saved == []
    assert "four" in db.rows["clients"][0]["generation_error"]


def test_select_images_prioritizes_never_used_over_expired():
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    available = images(6)
    history = [{"drive_file_id": "file-0", "last_used_at": (now - timedelta(weeks=4)).isoformat()},
               {"drive_file_id": "file-1", "last_used_at": (now - timedelta(weeks=1)).isoformat()}]
    selected, recycled = jobs.seleccionar_imagenes(available, history, now)
    assert [item[0] for item in selected] == ["file-2", "file-3", "file-4", "file-5"]
    assert recycled is False


def test_select_images_uses_expired_before_recent_and_marks_recycling():
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    available = images(4)
    history = [{"drive_file_id": f"file-{i}",
                "last_used_at": (now - timedelta(weeks=1 + i)).isoformat()}
               for i in range(4)]
    selected, recycled = jobs.seleccionar_imagenes(available, history, now)
    assert [item[0] for item in selected] == ["file-3", "file-2", "file-1", "file-0"]
    assert recycled is True


def test_weekly_recycling_logs_a_warning_without_touching_generation_error(generation, caplog):
    now = datetime.now(timezone.utc)
    _, engine = generation
    db = Database([client()])
    db.rows["client_images"] = [{"client_id": "good", "drive_file_id": f"file-{i}",
        "last_used_at": (now - timedelta(days=1)).isoformat()} for i in range(3)]
    engine.return_value = HiloGenerado(
        historias=[f"Story {i}" for i in range(4)],
        imagenes_originales_url=[f"raw-{i}" for i in range(4)],
        imagenes_editadas_url=[f"edited-{i}" for i in range(4)],
        drive_file_ids_usados=["file-3", "file-4", "file-0", "file-1"],
    )
    with caplog.at_level("WARNING"):
        jobs.generate_weekly(db, date(2026, 9, 18))
    # Recycling is a benign, informational event: it must not be written into
    # generation_error, which is documented (AGENTS.md) as "the last generation
    # error" and gets cleared on every successful, persisted generation.
    assert len(db.saved) == 1
    assert "generation_error" not in db.rows["clients"][0]
    assert any("pool_bajo" in record.message for record in caplog.records)


def story(id="story", **updates):
    row = dict(id=id, story_group_id="group", client_id="good", order=1,
               image_url="edited", fecha_publicacion="2026-09-21", estado="pendiente",
               agregar_cta=True, aprobado=True, clients={"instagram_account_id": "ig",
               "meta_access_token_encrypted": "encrypted", "calendly_link": "booking"})
    row.update(updates)
    return row


@pytest.fixture
def publication(monkeypatch):
    engine = Mock(return_value=ResultadoPublicacion(ok=True, ig_media_id="media"))
    decrypt = Mock(return_value="plain-token")
    monkeypatch.setattr(jobs.content, "publicar_historia", engine)
    monkeypatch.setattr(jobs, "decrypt", decrypt)
    return engine, decrypt


def test_publication_success_uses_decrypted_token_and_only_pending_today(publication):
    engine, decrypt = publication
    db = Database(stories=[story(), story("future", fecha_publicacion="2026-09-22"),
                          story("old", estado="error")])
    jobs.publish_daily(db, date(2026, 9, 21))
    engine.assert_called_once_with(image_url="edited", instagram_account_id="ig",
        meta_access_token="plain-token", agregar_cta=True, calendly_link="booking")
    decrypt.assert_called_once_with("encrypted")
    assert db.rows["stories"][0]["estado"] == "publicado"
    assert db.rows["stories"][0]["ig_media_id"] == "media"
    assert db.rows["stories"][1]["estado"] == "pendiente"
    assert db.rows["stories"][2]["estado"] == "error"


@pytest.mark.parametrize("failure", [MetaPublishError("Meta failed"),
    ResultadoPublicacion(ok=False, error="Meta failed")])
def test_publication_error_is_saved_and_next_story_runs(publication, failure):
    engine, _ = publication
    engine.side_effect = [failure, ResultadoPublicacion(ok=True, ig_media_id="second")]
    db = Database(stories=[story(), story("next", order=2)])
    jobs.publish_daily(db, date(2026, 9, 21))
    assert db.rows["stories"][0]["estado"] == "error"
    assert db.rows["stories"][0]["error"] == "Meta failed"
    assert db.rows["stories"][1]["estado"] == "publicado"
    jobs.publish_daily(db, date(2026, 9, 21))
    assert engine.call_count == 2  # No automatic retries of errors or published rows.


def test_encryption_failure_never_calls_meta(publication):
    engine, decrypt = publication
    decrypt.side_effect = ValueError("Token de cifrado inválido o alterado")
    db = Database(stories=[story()])
    jobs.publish_daily(db, date(2026, 9, 21))
    engine.assert_not_called()
    assert db.rows["stories"][0]["estado"] == "error"
    assert "cifrado" in db.rows["stories"][0]["error"]


def test_unapproved_manual_story_never_publishes(publication):
    engine, _ = publication
    db = Database(stories=[story(aprobado=False)])
    jobs.publish_daily(db, date(2026, 9, 21))
    engine.assert_not_called()
    assert db.rows["stories"][0]["estado"] == "pendiente"


def test_publish_now_ignores_date_and_hour_gates(publication):
    engine, _ = publication
    db = Database(stories=[story(fecha_publicacion="2099-01-01", hora_publicacion="23:59:00")])

    result = jobs.publish_now(db, "good", "2099-01-01")

    engine.assert_called_once()
    assert db.rows["stories"][0]["estado"] == "publicado"
    assert result == {"publicadas": 1, "fallidas": 0}


def test_publish_now_retries_a_previously_failed_story(publication):
    engine, _ = publication
    db = Database(stories=[story(estado="error", error="Meta failed")])

    result = jobs.publish_now(db, "good", "2026-09-21")

    engine.assert_called_once()
    assert db.rows["stories"][0]["estado"] == "publicado"
    assert result == {"publicadas": 1, "fallidas": 0}


def test_publish_now_does_not_retry_published_cancelled_or_in_flight_stories(publication):
    engine, _ = publication
    db = Database(stories=[
        story("done", estado="publicado"),
        story("cancelled", estado="cancelada"),
        story("mid", estado="publicando"),
    ])

    result = jobs.publish_now(db, "good", "2026-09-21")

    engine.assert_not_called()
    assert result == {"publicadas": 0, "fallidas": 0}


def test_publish_now_skips_unapproved_and_other_clients_or_dates(publication):
    engine, _ = publication
    db = Database(stories=[
        story(aprobado=False),
        story("other-client", client_id="other"),
        story("other-date", fecha_publicacion="2026-09-22"),
    ])

    result = jobs.publish_now(db, "good", "2026-09-21")

    engine.assert_not_called()
    assert result == {"publicadas": 0, "fallidas": 0}


def test_publish_now_counts_failures(publication):
    engine, _ = publication
    engine.side_effect = MetaPublishError("Meta failed")
    db = Database(stories=[story()])

    result = jobs.publish_now(db, "good", "2026-09-21")

    assert result == {"publicadas": 0, "fallidas": 1}
    assert db.rows["stories"][0]["estado"] == "error"
