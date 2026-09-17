-- Apply after 20260917_a5_spread_weekly_stories.sql.
-- Per-client publishing cadence ("ritmo"): which 4 weekdays (0=Mon..6=Sun)
-- the weekly thread publishes on. Null means "use the global default"
-- (PUBLISH_DAY_OFFSETS in content_jobs.py, currently Mon/Wed/Fri/Sun).
begin;

alter table public.clients
  add column if not exists publish_days jsonb;

commit;
