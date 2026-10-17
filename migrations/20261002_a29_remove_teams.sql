-- a29: remove the "Equipo" (team) concept entirely. PMs see only their own
-- assigned clients via employee_clients ("Mostrar solo mis clientes"), not a
-- separate team/category layer — that's the real org structure, teams never
-- was. Drop columns before the table so there's no FK-dependency error.
alter table clients drop column if exists team_id;
alter table employees drop column if exists team_id;
drop table if exists teams;
