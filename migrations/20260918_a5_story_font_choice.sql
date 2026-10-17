-- Apply after 20260918_a5_client_font_choice.sql.
-- Per-story typography override: lets an employee pick a different font
-- for one specific Story image than the client's default (clients.font_choice).
-- Nullable: null means "use the client's default font, or the engine's
-- historical fallback if the client has none" — every existing story is
-- unaffected.
begin;

alter table public.stories
  add column if not exists font_choice text;

commit;
