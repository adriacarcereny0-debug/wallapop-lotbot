-- Usuario SOLO DE LECTURA para la copia de seguridad diaria (esquema lotbot).
-- Ejecutar en Neon → SQL Editor, base «neondb», rama «main», como neondb_owner.
-- Antes de ejecutar: cambia CAMBIA_ESTA_CONTRASEÑA por una contraseña larga y
-- aleatoria (32+ caracteres, sin comillas simples) generada en tu gestor.
--
-- Por qué así y no desde el panel «Roles» de Neon: los usuarios creados en el
-- panel entran en neon_superuser, que puede ESCRIBIR en todas las tablas.
-- BYPASSRLS: las tablas de lotbot tienen RLS sin políticas; sin él pg_dump
-- no puede leerlas. No da permiso de escritura.

CREATE ROLE lotbot_copia WITH LOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE
  CONNECTION LIMIT 3 PASSWORD 'CAMBIA_ESTA_CONTRASEÑA';

-- Cualquier sesión de este usuario es de solo lectura, aunque un día se le
-- diera un permiso de más por error.
ALTER ROLE lotbot_copia SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE neondb TO lotbot_copia;
GRANT USAGE ON SCHEMA lotbot TO lotbot_copia;
GRANT SELECT ON ALL TABLES IN SCHEMA lotbot TO lotbot_copia;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA lotbot TO lotbot_copia;
-- Tablas que creen migraciones futuras: también solo lectura.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA lotbot GRANT SELECT ON TABLES TO lotbot_copia;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA lotbot GRANT SELECT ON SEQUENCES TO lotbot_copia;
