-- Allow the employee portal to soft-delete stories without removing history.
begin;

alter table public.stories drop constraint if exists stories_estado_check;
alter table public.stories add constraint stories_estado_check
  check (estado in ('pendiente', 'publicando', 'publicado', 'error', 'cancelada'));

-- Swapping positions cannot be expressed as separate UPDATE requests while the
-- unique constraint is immediate. Make it deferable and perform the swap in one transaction.
alter table public.stories drop constraint if exists stories_story_group_id_order_key;
alter table public.stories add constraint stories_story_group_id_order_key
  unique (story_group_id, "order") deferrable initially immediate;

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
  -- Cancelled rows remain hidden history. Move them behind the visible sequence
  -- so active positions can stay contiguous without colliding with soft deletes.
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

create or replace function public.update_client_prompt(
  p_client_id uuid,
  p_employee_id uuid,
  p_agency_id uuid,
  p_patch jsonb
) returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_before public.clients%rowtype;
  v_after public.clients%rowtype;
begin
  if jsonb_typeof(p_patch) is distinct from 'object' then
    raise exception 'Prompt patch must be an object';
  end if;
  if exists (
    select 1 from jsonb_object_keys(p_patch) field
    where field <> all (array[
      'business_description', 'weekly_focus', 'weekly_focus_expires_at',
      'tone_examples', 'topics'
    ])
  ) then
    raise exception 'Prompt patch contains unsupported fields';
  end if;
  if not exists (
    select 1 from public.employees
    where id = p_employee_id and agency_id = p_agency_id and active is true
  ) then
    raise insufficient_privilege using message = 'Employee is outside the agency';
  end if;

  select * into v_before from public.clients where id = p_client_id for update;
  if not found then
    raise no_data_found using message = 'Client not found';
  end if;
  if v_before.agency_id <> p_agency_id then
    raise insufficient_privilege using message = 'Client is outside the agency';
  end if;
  if p_patch ? 'tone_examples'
     and jsonb_typeof(p_patch->'tone_examples') is distinct from 'array' then
    raise exception 'tone_examples must be an array';
  end if;
  if p_patch ? 'topics'
     and jsonb_typeof(p_patch->'topics') not in ('array', 'null') then
    raise exception 'topics must be an array or null';
  end if;

  update public.clients set
    business_description = case when p_patch ? 'business_description'
      then p_patch->>'business_description' else business_description end,
    weekly_focus = case when p_patch ? 'weekly_focus'
      then p_patch->>'weekly_focus' else weekly_focus end,
    weekly_focus_expires_at = case when p_patch ? 'weekly_focus_expires_at'
      then (p_patch->>'weekly_focus_expires_at')::date else weekly_focus_expires_at end,
    tone_examples = case when p_patch ? 'tone_examples'
      then p_patch->'tone_examples' else tone_examples end,
    topics = case when p_patch ? 'topics'
      then p_patch->'topics' else topics end
  where id = p_client_id
  returning * into v_after;

  if v_before.business_description is distinct from v_after.business_description then
    insert into public.prompt_history(client_id, changed_by, field, old_value, new_value)
    values (p_client_id, p_employee_id, 'business_description',
      v_before.business_description, v_after.business_description);
  end if;
  if v_before.weekly_focus is distinct from v_after.weekly_focus then
    insert into public.prompt_history(client_id, changed_by, field, old_value, new_value)
    values (p_client_id, p_employee_id, 'weekly_focus',
      v_before.weekly_focus, v_after.weekly_focus);
  end if;
  if v_before.tone_examples is distinct from v_after.tone_examples then
    insert into public.prompt_history(client_id, changed_by, field, old_value, new_value)
    values (p_client_id, p_employee_id, 'tone_examples',
      v_before.tone_examples::text, v_after.tone_examples::text);
  end if;
  if v_before.topics is distinct from v_after.topics then
    insert into public.prompt_history(client_id, changed_by, field, old_value, new_value)
    values (p_client_id, p_employee_id, 'topics',
      v_before.topics::text, v_after.topics::text);
  end if;
  return to_jsonb(v_after);
end;
$$;

revoke all on function public.update_client_prompt(uuid, uuid, uuid, jsonb)
  from public, anon, authenticated;
grant execute on function public.update_client_prompt(uuid, uuid, uuid, jsonb)
  to service_role;

commit;
