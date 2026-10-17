-- a41: avatar propio del cliente para personalizar el portal — columna nueva
-- y separada de logo_url (que ya existe y el motor usa para componer un logo
-- sobre las historias generadas, app/engine/content.py::_descargar_logo).
-- avatar_url es PURAMENTE visual para el portal, nunca se le pasa al motor.
-- instagram_profile_url/whatsapp_contact/contact_email son información de
-- contacto nueva, sin relación con instagram_account_id (ID de cuenta de la
-- API de Meta) ni wa_phone_encrypted (número encriptado del flujo de
-- aprobación por WhatsApp, sin usar hoy).
alter table clients add column if not exists avatar_url text;
alter table clients add column if not exists avatar_public_id text;
alter table clients add column if not exists instagram_profile_url text;
alter table clients add column if not exists whatsapp_contact text;
alter table clients add column if not exists contact_email text;
