-- Apply after 20260915_a4_portal_cancelled_stories.sql.
-- "Equipos": subdivisión de una agencia (varios empleados, varios clientes a
-- su cargo) para que a los empleados les sea más fácil encontrar sus clientes
-- en el panel. Puramente organizativo: no cambia permisos ni el contrato del
-- engine, solo agrupa/etiqueta filas ya existentes.
begin;

create table if not exists public.teams (
  id uuid primary key default uuid_generate_v4(),
  agency_id uuid not null references public.agencies(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (agency_id, name)
);

alter table public.employees
  add column if not exists team_id uuid references public.teams(id) on delete set null;

alter table public.clients
  add column if not exists team_id uuid references public.teams(id) on delete set null;

create index if not exists teams_agency_id_idx on public.teams(agency_id);
create index if not exists employees_team_id_idx on public.employees(team_id);
create index if not exists clients_team_id_idx on public.clients(team_id);

-- Backend-only, same pattern as client_images/employee_clients/prompt_history:
-- only the FastAPI service (service_role) reads/writes this table.
alter table public.teams enable row level security;
grant all on public.teams to service_role;

commit;
