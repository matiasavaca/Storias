alter table clients
  add column if not exists publish_together boolean not null default false;
