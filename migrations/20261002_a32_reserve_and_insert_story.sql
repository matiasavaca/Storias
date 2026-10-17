-- A32: reserve a generated Story slot before calling Claude or Cloudinary.
-- The transient story row protects the existing unique(group_id, order)
-- invariant while the expensive work happens outside the short reservation RPC.
begin;

alter table public.stories drop constraint if exists stories_estado_check;
alter table public.stories add constraint stories_estado_check
  check (estado in ('pendiente', 'generando', 'publicando', 'publicado', 'error', 'cancelada'));

drop function if exists public.reserve_and_insert_story(uuid, jsonb);

create or replace function public.reserve_generated_story(
  p_group_id uuid,
  p_client_id uuid,
  p_agency_id uuid,
  p_fecha_publicacion date,
  p_hora_publicacion time
) returns public.stories
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_group public.story_groups%rowtype;
  v_next_order integer;
  v_row public.stories%rowtype;
begin
  if p_group_id is null or p_client_id is null or p_agency_id is null
     or p_fecha_publicacion is null or p_hora_publicacion is null then
    raise exception 'Group, client, agency and schedule are required';
  end if;

  perform pg_advisory_xact_lock(hashtext(p_group_id::text));

  perform 1 from public.clients
   where id = p_client_id and agency_id = p_agency_id
   for key share;
  if not found then
    raise insufficient_privilege using message = 'Client is outside the agency';
  end if;

  select * into v_group from public.story_groups
   where id = p_group_id
     and client_id = p_client_id
     and agency_id = p_agency_id
   for update;
  if not found then
    raise exception 'Manual group does not exist for this client';
  end if;
  if v_group.generation_week is not null
     or v_group.manual_duplicate_of is not null
     or v_group.agendado is true
     or v_group.status <> 'pending'
     or v_group.scheduled_date <> p_fecha_publicacion then
    raise exception 'Manual group is not available for generated stories';
  end if;

  select coalesce(max("order"), 0) + 1 into v_next_order
    from public.stories where story_group_id = p_group_id;
  if v_next_order > 10 then
    raise exception 'Manual group already has ten stories';
  end if;

  insert into public.stories (
    story_group_id, client_id, "order", text, fecha_publicacion,
    hora_publicacion, estado, agregar_cta, aprobado
  ) values (
    p_group_id, p_client_id, v_next_order, '', p_fecha_publicacion,
    p_hora_publicacion, 'generando', false, false
  ) returning * into v_row;

  return v_row;
end;
$$;

-- a32 (addendum): finalize_reserved_generated_story needs this unique index
-- for the client_images upsert below. Earlier code used a SELECT + branch
-- and therefore did not require a conflict target in the database.
create unique index if not exists client_images_client_drive_key
  on public.client_images (client_id, drive_file_id);

create or replace function public.finalize_reserved_generated_story(
  p_story_id uuid,
  p_story jsonb,
  p_image jsonb
) returns public.stories
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_reserved public.stories%rowtype;
  v_group public.story_groups%rowtype;
  v_row public.stories%rowtype;
  v_client_id uuid;
  v_fecha_publicacion date;
  v_hora_publicacion time;
begin
  if jsonb_typeof(p_story) is distinct from 'object'
     or jsonb_typeof(p_image) is distinct from 'object' then
    raise exception 'Story and image payloads are required';
  end if;

  select * into v_reserved from public.stories
   where id = p_story_id and estado = 'generando'
   for update;
  if not found then
    raise exception 'Generated story reservation does not exist';
  end if;

  select * into v_group from public.story_groups
   where id = v_reserved.story_group_id
   for update;
  if not found then
    raise exception 'Reserved story group does not exist';
  end if;
  if v_group.client_id <> v_reserved.client_id
     or v_group.scheduled_date <> v_reserved.fecha_publicacion
     or v_group.generation_week is not null
     or v_group.manual_duplicate_of is not null
     or v_group.agendado is true
     or v_group.status <> 'pending'
     or not exists (
       select 1 from public.clients
        where id = v_reserved.client_id and agency_id = v_group.agency_id
     ) then
    raise exception 'Reserved story group is no longer available';
  end if;
  if coalesce(p_story->>'client_id', '') = ''
     or coalesce(p_story->>'fecha_publicacion', '') = ''
     or coalesce(p_story->>'hora_publicacion', '') = ''
     or coalesce(p_story->>'text', '') = ''
     or coalesce(p_story->>'image_url', '') = ''
     or coalesce(p_story->>'image_original_url', '') = ''
     or coalesce(p_image->>'drive_file_id', '') = ''
     or coalesce(p_image->>'drive_file_name', '') = '' then
    raise exception 'Story text, URLs, schedule and named Drive image are required';
  end if;

  v_client_id := (p_story->>'client_id')::uuid;
  v_fecha_publicacion := (p_story->>'fecha_publicacion')::date;
  v_hora_publicacion := (p_story->>'hora_publicacion')::time;
  if v_client_id <> v_reserved.client_id then
    raise exception 'Reserved story belongs to another client';
  end if;
  if v_fecha_publicacion <> v_reserved.fecha_publicacion
     or v_hora_publicacion <> v_reserved.hora_publicacion then
    raise exception 'Reserved story schedule changed';
  end if;

  update public.stories set
    text = p_story->>'text',
    image_url = p_story->>'image_url',
    image_original_url = p_story->>'image_original_url',
    fecha_publicacion = v_fecha_publicacion,
    hora_publicacion = v_hora_publicacion,
    estado = 'pendiente',
    agregar_cta = coalesce((p_story->>'agregar_cta')::boolean, false),
    aprobado = coalesce((p_story->>'aprobado')::boolean, false)
  where id = p_story_id
  returning * into v_row;

  insert into public.client_images (
    client_id, drive_file_id, drive_file_name, last_used_at, times_used
  ) values (
    v_reserved.client_id, p_image->>'drive_file_id', p_image->>'drive_file_name', now(), 1
  ) on conflict (client_id, drive_file_id) do update
    set drive_file_name = excluded.drive_file_name,
        last_used_at = excluded.last_used_at,
        times_used = public.client_images.times_used + 1;

  return v_row;
end;
$$;

create or replace function public.release_reserved_generated_story(
  p_story_id uuid
) returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_group_id uuid;
begin
  delete from public.stories
   where id = p_story_id and estado = 'generando'
   returning story_group_id into v_group_id;
  return v_group_id;
end;
$$;

revoke all on function public.reserve_generated_story(uuid, uuid, uuid, date, time)
  from public, anon, authenticated;
revoke all on function public.finalize_reserved_generated_story(uuid, jsonb, jsonb)
  from public, anon, authenticated;
revoke all on function public.release_reserved_generated_story(uuid)
  from public, anon, authenticated;
grant execute on function public.reserve_generated_story(uuid, uuid, uuid, date, time)
  to service_role;
grant execute on function public.finalize_reserved_generated_story(uuid, jsonb, jsonb)
  to service_role;
grant execute on function public.release_reserved_generated_story(uuid)
  to service_role;

commit;
