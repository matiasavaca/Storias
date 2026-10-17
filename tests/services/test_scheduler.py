from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import scheduler


def test_beat_has_weekly_friday_and_configured_daily_schedule():
    settings = Settings(publication_hour=11, publication_minute=25)
    app = scheduler._make_celery(settings)
    schedules = app.conf.beat_schedule
    assert app.conf.timezone == "America/Argentina/Buenos_Aires"
    weekly = schedules["generate-weekly-threads"]
    assert weekly["task"] == "app.services.scheduler.generar_hilos_semanales"
    assert weekly["schedule"].day_of_week == {5}
    assert weekly["schedule"].hour == {18} and weekly["schedule"].minute == {0}
    daily = schedules["publish-daily-stories"]
    assert daily["task"] == "app.services.scheduler.publicar_historias_pendientes"
    # Every 1 min (all 24 hours), not every 15 — each client can have its own
    # per-day publish time (content_jobs.publish_schedule) down to the exact
    # minute, so this has to check as close to continuously as practical
    # instead of waiting up to ~14 min for the next fixed 15-min tick.
    assert daily["schedule"].minute == set(range(60))
    assert daily["schedule"].hour == set(range(24))


@pytest.mark.parametrize("task_name,worker", [("publicar_historias_pendientes", "publish_daily")])
def test_task_dispatches_to_portal_with_admin_database(monkeypatch, task_name, worker):
    from app.db import supabase
    from app.services import content_jobs
    db = object()
    monkeypatch.setattr(supabase, "get_admin_client", lambda: db)
    runner = Mock()
    monkeypatch.setattr(content_jobs, worker, runner)
    getattr(scheduler, task_name).run()
    runner.assert_called_once_with(db)


def test_generar_hilos_semanales_dispatches_one_task_per_active_client(monkeypatch):
    from app.db import supabase

    class FakeDb:
        def table(self, name):
            assert name == "clients"
            return self

        def select(self, *_): return self
        def eq(self, *_): return self
        def execute(self):
            return SimpleNamespace(data=[{"id": "a"}, {"id": "b"}, {"id": "c"}])

    monkeypatch.setattr(supabase, "get_admin_client", lambda: FakeDb())
    dispatched = Mock()
    monkeypatch.setattr(scheduler.generar_hilo_cliente, "delay", dispatched)

    scheduler.generar_hilos_semanales.run()

    assert dispatched.call_count == 3
    assert {call.args[0] for call in dispatched.call_args_list} == {"a", "b", "c"}


def test_generar_hilos_semanales_dispatches_nothing_with_no_active_clients(monkeypatch):
    from app.db import supabase

    class FakeDb:
        def table(self, _): return self
        def select(self, *_): return self
        def eq(self, *_): return self
        def execute(self): return SimpleNamespace(data=[])

    monkeypatch.setattr(supabase, "get_admin_client", lambda: FakeDb())
    dispatched = Mock()
    monkeypatch.setattr(scheduler.generar_hilo_cliente, "delay", dispatched)

    scheduler.generar_hilos_semanales.run()

    dispatched.assert_not_called()


def test_generar_hilo_cliente_dispatches_single_client_to_portal(monkeypatch):
    from app.db import supabase
    from app.services import content_jobs

    db = object()
    monkeypatch.setattr(supabase, "get_admin_client", lambda: db)
    runner = Mock()
    monkeypatch.setattr(content_jobs, "generate_for_client_by_id", runner)

    scheduler.generar_hilo_cliente.run("client-123")

    runner.assert_called_once_with(db, "client-123")


@pytest.mark.parametrize("setting,value", [("publication_hour", 24), ("publication_minute", -1)])
def test_invalid_schedule_is_rejected(setting, value):
    with pytest.raises(ValidationError):
        Settings(**{setting: value})
