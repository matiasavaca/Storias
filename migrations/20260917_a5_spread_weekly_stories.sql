-- Apply after 20260916_a5_teams.sql.
-- Each story in a weekly thread now carries its own fecha_publicacion
-- (spread across the week: Mon/Wed/Fri/Sun) instead of all four sharing
-- the group's single p_scheduled_date. publish_daily already filters
-- stories by their own fecha_publicacion, so it needs no changes.
-- Falls back to p_scheduled_date when a story omits fecha_publicacion,
-- so this stays compatible with any caller still on the old shape.
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
      image_original_url, fecha_publicacion, estado, agregar_cta)
    values (v_group_id, p_client_id, v_position, v_story->>'text', v_story->>'image_url',
      v_story->>'image_original_url',
      coalesce((v_story->>'fecha_publicacion')::date, p_scheduled_date), 'pendiente',
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
