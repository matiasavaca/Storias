-- Apply after 20260918_a5_story_approval.sql.
-- Internal, employee-only note on a manually-scheduled day's thread ("¿de qué
-- va este hilo?") — never shown to the client, never rendered on the image.
-- Purely a planning aid, shown as the title in the "Plan de la próxima
-- semana" preview once the day is agendado.
begin;

alter table public.story_groups
  add column if not exists descripcion text;

commit;
