-- Apply after 20260917_a5_publish_hour.sql.
-- Approval gate for manually-uploaded stories: they start unapproved and
-- publish_daily() now skips anything not approved. Defaults to true so every
-- existing row (and every AI-generated story going forward, which is already
-- reviewed via the text-edit flow) keeps publishing exactly as before —
-- only the manual-upload endpoint ever inserts a row with aprobado = false.
--
-- story_groups.agendado marks a manual day as confirmed-scheduled once every
-- one of its stories is approved — that's what moves it out of "Historias
-- generadas" and into the small "Plan de la próxima semana" preview.
-- Defaults to false; AI batches never set it and are unaffected.
begin;

alter table public.stories
  add column if not exists aprobado boolean not null default true;

alter table public.story_groups
  add column if not exists agendado boolean not null default false;

commit;
