-- Apply after the original supabase_schema.sql on existing installations.
begin;

alter table public.clients
  add column if not exists business_description text,
  add column if not exists tone_examples jsonb not null default '[]'::jsonb,
  add column if not exists topics jsonb,
  add column if not exists weekly_focus text,
  add column if not exists weekly_focus_expires_at date,
  add column if not exists drive_folder_id text,
  add column if not exists logo_url text,
  add column if not exists calendly_link text,
  add column if not exists prob_link double precision not null default 0,
  add column if not exists generation_error text,
  add column if not exists generation_error_at timestamptz;

create table if not exists public.client_images (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.clients(id) on delete cascade,
  drive_file_id text not null,
  drive_file_name text not null,
  last_used_at timestamptz,
  times_used integer not null default 0 check (times_used >= 0),
  unique (client_id, drive_file_id)
);

create table if not exists public.employee_clients (
  employee_id uuid not null references public.employees(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  primary key (employee_id, client_id)
);

create table if not exists public.prompt_history (
  id uuid primary key default uuid_generate_v4(),
  client_id uuid not null references public.clients(id) on delete cascade,
  changed_by uuid references public.employees(id) on delete set null,
  field text not null check (field in ('business_description', 'weekly_focus', 'tone_examples', 'topics')),
  old_value text,
  new_value text,
  changed_at timestamptz not null default now()
);

alter table public.story_groups add column if not exists generation_week date;
alter table public.story_groups drop constraint if exists story_groups_status_check;
alter table public.story_groups add constraint story_groups_status_check
  check (status in ('draft', 'pending_approval', 'approved', 'published', 'failed', 'pending'));
create unique index if not exists story_groups_generation_week_idx
  on public.story_groups(client_id, generation_week) where generation_week is not null;

alter table public.stories
  add column if not exists image_original_url text,
  add column if not exists fecha_publicacion date,
  add column if not exists estado text check (estado in ('pendiente', 'publicando', 'publicado', 'error')),
  add column if not exists error text,
  add column if not exists agregar_cta boolean not null default false,
  add column if not exists published_at timestamptz;
create index if not exists stories_pending_publication_idx
  on public.stories(fecha_publicacion, story_group_id, "order") where estado = 'pendiente';
create index if not exists prompt_history_client_idx on public.prompt_history(client_id, changed_at);
create index if not exists employee_clients_client_idx on public.employee_clients(client_id);

-- Backend-only until A4 adds employee assignment/audit access rules.
-- Existing table policies and legacy rows are unchanged.
alter table public.client_images enable row level security;
alter table public.employee_clients enable row level security;
alter table public.prompt_history enable row level security;
grant all on public.client_images, public.employee_clients, public.prompt_history to service_role;

create or replace function public.persist_generated_thread(
  p_client_id uuid,
  p_generation_week date,
  p_scheduled_date date,
  p_scheduled_time time,
  p_stories jsonb,
  p_images jsonb,
  p_used_focus text,
  p_used_focus_expires_at date
) returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_client public.clients%rowtype;
  v_group_id uuid;
  v_story jsonb;
  v_position integer := 0;
begin
  if p_generation_week is null or p_scheduled_date is null or p_scheduled_time is null then
    raise exception 'Generation week and publication schedule are required';
  end if;
  if jsonb_typeof(p_stories) is distinct from 'array'
     or jsonb_typeof(p_images) is distinct from 'array' then
    raise exception 'Expected four stories and four images';
  end if;
  if jsonb_array_length(p_stories) <> 4 or jsonb_array_length(p_images) <> 4 then
    raise exception 'Expected four stories and four images';
  end if;
  if (select count(distinct item->>'drive_file_id') from jsonb_array_elements(p_images) item) <> 4
     or exists (select 1 from jsonb_array_elements(p_images) item
                where coalesce(item->>'drive_file_id', '') = ''
                   or coalesce(item->>'drive_file_name', '') = '') then
    raise exception 'Expected four distinct named Drive images';
  end if;

  select * into strict v_client from public.clients where id = p_client_id for update;
  insert into public.story_groups (client_id, agency_id, scheduled_date, scheduled_time, status, generation_week)
  values (p_client_id, v_client.agency_id, p_scheduled_date, p_scheduled_time, 'pending', p_generation_week)
  on conflict (client_id, generation_week) where generation_week is not null do nothing
  returning id into v_group_id;
  if v_group_id is null then
    select id into v_group_id from public.story_groups
      where client_id = p_client_id and generation_week = p_generation_week;
    return v_group_id;
  end if;

  for v_story in select value from jsonb_array_elements(p_stories) loop
    v_position := v_position + 1;
    if coalesce(v_story->>'text', '') = '' or coalesce(v_story->>'image_url', '') = ''
       or coalesce(v_story->>'image_original_url', '') = '' then
      raise exception 'Every story requires text, edited URL and original URL';
    end if;
    insert into public.stories (story_group_id, client_id, "order", text, image_url,
      image_original_url, fecha_publicacion, estado, agregar_cta)
    values (v_group_id, p_client_id, v_position, v_story->>'text', v_story->>'image_url',
      v_story->>'image_original_url', p_scheduled_date, 'pendiente',
      coalesce((v_story->>'agregar_cta')::boolean, false));
  end loop;

  insert into public.client_images (client_id, drive_file_id, drive_file_name, last_used_at, times_used)
    select p_client_id, item->>'drive_file_id', item->>'drive_file_name', now(), 1
    from jsonb_array_elements(p_images) item
  on conflict (client_id, drive_file_id) do update
    set drive_file_name = excluded.drive_file_name,
        last_used_at = excluded.last_used_at,
        times_used = public.client_images.times_used + 1;

  update public.clients set generation_error = null, generation_error_at = null
    where id = p_client_id;
  if p_used_focus is not null and p_used_focus <> '' then
    update public.clients set weekly_focus = null, weekly_focus_expires_at = null
      where id = p_client_id and weekly_focus = p_used_focus
        and weekly_focus_expires_at is not distinct from p_used_focus_expires_at;
  end if;
  return v_group_id;
end;
$$;

revoke all on function public.persist_generated_thread(uuid, date, date, time, jsonb, jsonb, text, date)
  from public, anon, authenticated;
grant execute on function public.persist_generated_thread(uuid, date, date, time, jsonb, jsonb, text, date)
  to service_role;

commit;
