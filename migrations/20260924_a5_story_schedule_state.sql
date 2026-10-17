-- A weekly AI group spans multiple publication dates, so confirmation belongs
-- to each story/date. story_groups.agendado remains a legacy completion summary.
alter table public.stories
  add column if not exists agendado boolean not null default false;

-- Preserve already-confirmed legacy groups when deploying this migration.
update public.stories as stories
set agendado = true
from public.story_groups as groups
where stories.story_group_id = groups.id
  and groups.agendado = true
  and stories.agendado = false;

create index if not exists stories_schedule_state_idx
  on public.stories(client_id, fecha_publicacion, agendado)
  where estado is distinct from 'cancelada';
