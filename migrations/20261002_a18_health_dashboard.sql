-- a18: persist whether a client's latest weekly generation had to recycle
-- images because its available pool was too small. This used to exist only
-- in worker logs, so the agency health dashboard could not surface it.
-- NULL means the latest generation did not recycle images (or none ran yet).
alter table clients add column if not exists pool_bajo_at timestamptz;
