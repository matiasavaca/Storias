-- Remove a failed first-upload reservation without racing a concurrent story
-- insert. The NOT EXISTS check and DELETE run as one database statement.
begin;

create or replace function public.delete_empty_manual_group(p_group_id uuid)
returns boolean
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_deleted boolean := false;
begin
  -- Serialize against a concurrent story INSERT. The FK check for that INSERT
  -- takes a key-share lock on this row, which conflicts with FOR UPDATE: either
  -- the story commits first and the check below preserves the group, or this
  -- transaction deletes first and the later INSERT fails its FK. This prevents
  -- ON DELETE CASCADE from consuming a concurrently-created story.
  perform 1
    from public.story_groups groups
   where groups.id = p_group_id
     and groups.generation_week is null
     and groups.manual_duplicate_of is null
     and groups.agendado = false
     and groups.status = 'pending'
   for update;

  if not found then
    return false;
  end if;

  delete from public.story_groups groups
   where groups.id = p_group_id
     and groups.generation_week is null
     and groups.manual_duplicate_of is null
     and groups.agendado = false
     and groups.status = 'pending'
     and not exists (
       select 1 from public.stories stories
        where stories.story_group_id = groups.id
     )
  returning true into v_deleted;

  return coalesce(v_deleted, false);
end;
$$;

revoke all on function public.delete_empty_manual_group(uuid)
  from public, anon, authenticated;
grant execute on function public.delete_empty_manual_group(uuid)
  to service_role;

commit;
