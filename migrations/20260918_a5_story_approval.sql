-- Apply after 20260917_a5_publish_hour.sql.
-- Approval gate for manually-uploaded stories: they start unapproved and
-- publish_daily() now skips anything not approved. Defaults to true so every
-- existing row (and every AI-generated story going forward, which is already
-- reviewed via the text-edit flow) keeps publishing exactly as before —
-- only the manual-upload endpoint ever inserts a row with aprobado = false.
begin;

alter table public.stories
  add column if not exists aprobado boolean not null default true;

commit;
