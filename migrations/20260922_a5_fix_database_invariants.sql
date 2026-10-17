-- Consolidate the final A5 database contract after all earlier A5 migrations.
--
-- 20260917_a5_spread_weekly_stories.sql is lexically applied after
-- 20260917_a5_publish_hour.sql and therefore replaced persist_generated_thread
-- with a version that kept per-story dates but stopped persisting per-story
-- times. Keep this migration self-contained so a fresh lexical migration run
-- and an upgrade of an existing database end with the same function body.
begin;

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
      image_original_url, fecha_publicacion, hora_publicacion, estado, agregar_cta)
    values (v_group_id, p_client_id, v_position, v_story->>'text', v_story->>'image_url',
      v_story->>'image_original_url',
      coalesce((v_story->>'fecha_publicacion')::date, p_scheduled_date),
      coalesce((v_story->>'hora_publicacion')::time, p_scheduled_time),
      'pendiente', coalesce((v_story->>'agregar_cta')::boolean, false));
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

-- Do not backfill existing NULL hora_publicacion values: scheduled_time stores
-- only the group's first slot, while A5 permits each story to use a different
-- local time. Copying it would manufacture an incorrect publication schedule.

create or replace function public.reorder_stories(p_orders jsonb) returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_group_id uuid;
  v_group_count integer;
  v_requested_count integer;
  v_active_count integer;
begin
  if jsonb_typeof(p_orders) is distinct from 'array' or jsonb_array_length(p_orders) = 0 then
    raise exception 'At least one story order is required';
  end if;
  select count(*), count(distinct s.story_group_id), min(s.story_group_id::text)::uuid
    into v_requested_count, v_group_count, v_group_id
    from public.stories s
    join jsonb_array_elements(p_orders) item on s.id = (item.value->>'story_id')::uuid;
  if v_requested_count <> jsonb_array_length(p_orders) or v_group_count <> 1 then
    raise exception 'Stories must exist and belong to the same group';
  end if;
  if (select count(distinct (item.value->>'new_order')::integer)
        from jsonb_array_elements(p_orders) item) <> jsonb_array_length(p_orders) then
    raise exception 'Story positions must be unique';
  end if;
  -- A group with an in-flight or published story is immutable. This prevents a
  -- PM reorder from changing the meaning/order of content already sent to Meta.
  if exists (
    select 1 from public.stories
    where story_group_id = v_group_id and estado in ('publicando', 'publicado')
  ) then
    raise exception 'Publishing or published stories cannot be reordered';
  end if;
  select count(*) into v_active_count from public.stories
   where story_group_id = v_group_id and estado is distinct from 'cancelada';
  if v_requested_count <> v_active_count or exists (
    select 1 from public.stories s
    join jsonb_array_elements(p_orders) item on s.id = (item.value->>'story_id')::uuid
    where s.estado = 'cancelada'
  ) then
    raise exception 'All and only active stories in the group must be ordered';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_orders) item
    where (item.value->>'new_order')::integer < 1
       or (item.value->>'new_order')::integer > v_active_count
  ) then
    raise exception 'Active story positions must be contiguous from one';
  end if;
  set constraints stories_story_group_id_order_key deferred;
  update public.stories s
     set "order" = (item.value->>'new_order')::integer
   from jsonb_array_elements(p_orders) item
   where s.id = (item.value->>'story_id')::uuid;
  with cancelled as (
    select id, row_number() over (order by "order", id) as offset
      from public.stories
     where story_group_id = v_group_id and estado = 'cancelada'
  )
  update public.stories s
     set "order" = v_active_count + cancelled.offset
    from cancelled
   where s.id = cancelled.id;
end;
$$;

revoke all on function public.reorder_stories(jsonb) from public, anon, authenticated;
grant execute on function public.reorder_stories(jsonb) to service_role;

-- A client has one canonical manual group per local publication day. Older
-- deployments allowed another group to be created after the first was marked
-- agendado. Preserve those groups and every story exactly as stored: moving
-- stories could change their per-group order or discard group-level status,
-- approval, schedule and description metadata. Instead, deterministically
-- quarantine every non-canonical legacy group behind the oldest group for that
-- client/date. New writes only use canonical groups and the partial unique
-- index prevents the legacy shape from being created again.
alter table public.story_groups
  add column if not exists manual_duplicate_of uuid
    references public.story_groups(id);

with ranked_manual_groups as (
  select id,
         first_value(id) over (
           partition by client_id, scheduled_date
           order by created_at asc nulls last, id asc
         ) as canonical_id,
         row_number() over (
           partition by client_id, scheduled_date
           order by created_at asc nulls last, id asc
         ) as duplicate_rank
    from public.story_groups
   where generation_week is null
     and manual_duplicate_of is null
)
update public.story_groups groups
   set manual_duplicate_of = ranked.canonical_id
  from ranked_manual_groups ranked
 where groups.id = ranked.id
   and ranked.duplicate_rank > 1;

create unique index if not exists story_groups_manual_client_date_idx
  on public.story_groups(client_id, scheduled_date)
  where generation_week is null and manual_duplicate_of is null;

commit;
