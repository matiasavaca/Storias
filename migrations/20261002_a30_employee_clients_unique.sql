-- fix a30: un cliente tiene a lo sumo un PM asignado. Esto lo garantiza la
-- base de datos (no solo el código), y habilita el upsert atómico de abajo
-- (ON CONFLICT necesita un índice único sobre la columna del conflicto).
-- Seguro de correr: employee_clients nunca tuvo datos hasta ahora.
create unique index if not exists employee_clients_client_id_key on employee_clients (client_id);
