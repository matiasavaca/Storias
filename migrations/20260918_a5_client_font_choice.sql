-- Apply after 20260918_a5_manual_thread_description.sql.
-- Per-client typography choice for the AI-composed Story images. Nullable:
-- null means "no choice made", and app.engine.imaging keeps falling back to
-- its historical default font — every existing client is unaffected.
begin;

alter table public.clients
  add column if not exists font_choice text;

commit;
