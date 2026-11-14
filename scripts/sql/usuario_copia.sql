-- Usuario SOLO DE LECTURA para la copia de seguridad diaria de LOT Bot.
--
-- DÓNDE: Neon → SQL Editor → rama «main» → base **neondb** (compruébalo en
-- el selector de base de datos ANTES de ejecutar) → como neondb_owner.
-- ANTES: cambia CAMBIA_ESTA_CONTRASEÑA por una contraseña de 32+ letras y
-- números (sin comillas ni símbolos) generada en tu gestor.
--
-- Es todo o nada: va en una transacción y, si cualquier comprobación falla,
-- no queda ningún cambio y el mensaje dice qué pasa. Se puede ejecutar varias
-- veces (si el usuario ya existe, se corrige). Al final comprueba él mismo
-- que el usuario lee las 17 tablas de lotbot y NADA más, y que no puede
-- escribir en ninguna parte.
--
-- LOT Bot = SOLO el esquema «lotbot» (17 tablas, ver web/src/lib/db.ts).
-- Todo lo demás de la base (p. ej. las tablas del CRM en «public») NO se
-- copia ni se puede leer con este usuario.

BEGIN;

-- 1. Comprobaciones previas y creación (si falta) ---------------------------
DO $$
DECLARE
  grupos text;
BEGIN
  IF current_database() <> 'neondb' THEN
    RAISE EXCEPTION 'Estás en la base «%»: elige «neondb» en el selector del SQL Editor y vuelve a ejecutar.', current_database();
  END IF;
  IF to_regnamespace('lotbot') IS NULL THEN
    RAISE EXCEPTION 'En esta base no existe el esquema «lotbot»: no es la base de LOT Bot.';
  END IF;
  IF current_user <> 'neondb_owner' THEN
    RAISE EXCEPTION 'Ejecuta como neondb_owner (ahora: %).', current_user;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lotbot_copia') THEN
    -- Un usuario creado desde el panel de Neon pertenece a neon_superuser
    -- (que puede escribir en todo): no se arregla, hay que borrarlo.
    SELECT string_agg(g.rolname, ', ') INTO grupos
      FROM pg_auth_members m
      JOIN pg_roles u ON u.oid = m.member
      JOIN pg_roles g ON g.oid = m.roleid
     WHERE u.rolname = 'lotbot_copia';
    IF grupos IS NOT NULL THEN
      RAISE EXCEPTION 'lotbot_copia pertenece a: %. Bórralo (Neon → Roles → lotbot_copia → Delete, o DROP ROLE lotbot_copia) y vuelve a ejecutar este script.', grupos;
    END IF;
  ELSE
    CREATE ROLE lotbot_copia LOGIN;
  END IF;
END $$;

-- 2. Atributos: solo entrar y saltarse RLS (las 17 tablas tienen RLS sin
--    políticas; sin BYPASSRLS se ven 0 filas y pg_dump falla). NOINHERIT: no
--    hereda permisos de ningún grupo aunque un día se le añada a uno.
--    (SUPERUSER, CREATEDB y REPLICATION no se nombran: desde PostgreSQL 16
--    neondb_owner no puede ni mencionarlos en ALTER ROLE; un usuario nuevo
--    nace sin ellos y el paso 6 lo comprueba.)
ALTER ROLE lotbot_copia WITH LOGIN BYPASSRLS NOINHERIT NOCREATEROLE
  CONNECTION LIMIT 3 PASSWORD 'CAMBIA_ESTA_CONTRASEÑA';
-- Segunda protección: toda sesión de este usuario es de solo lectura.
ALTER ROLE lotbot_copia SET default_transaction_read_only = on;

-- 3. Quitar cualquier permiso previo fuera de lo necesario -------------------
DO $$
DECLARE
  s text;
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace
            WHERE nspname NOT IN ('pg_catalog', 'information_schema')
              AND nspname NOT LIKE 'pg\_%'
  LOOP
    BEGIN
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM lotbot_copia', s);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM lotbot_copia', s);
      EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM lotbot_copia', s);
    EXCEPTION WHEN insufficient_privilege THEN
      -- Esquema de otro dueño al que neondb_owner no accede: si lotbot_copia
      -- tuviera algo ahí, lo detecta la comprobación final (paso 6).
      NULL;
    END;
  END LOOP;
END $$;
REVOKE ALL ON DATABASE neondb FROM lotbot_copia;

-- 4. Lo único que puede hacer: conectarse y LEER lotbot ----------------------
GRANT CONNECT ON DATABASE neondb TO lotbot_copia;
GRANT USAGE ON SCHEMA lotbot TO lotbot_copia;
GRANT SELECT ON ALL TABLES IN SCHEMA lotbot TO lotbot_copia;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA lotbot TO lotbot_copia;

-- 5. Tablas FUTURAS de LOT Bot: las crean las migraciones de la web, que se
--    conecta como neondb_owner (dueño de las 17 actuales). Lo que cree
--    neondb_owner en lotbot será legible automáticamente por lotbot_copia.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA lotbot GRANT SELECT ON TABLES TO lotbot_copia;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA lotbot GRANT SELECT ON SEQUENCES TO lotbot_copia;

-- 6. Comprobación final: si algo no cuadra, se deshace TODO ------------------
DO $$
DECLARE
  r record;
  sin_lectura text;
  lee_fuera text;
  escribe text;
  total int;
BEGIN
  SELECT * INTO r FROM pg_roles WHERE rolname = 'lotbot_copia';
  IF r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolinherit OR NOT r.rolbypassrls THEN
    RAISE EXCEPTION 'Atributos inesperados en lotbot_copia.';
  END IF;

  SELECT count(*) INTO total FROM pg_tables WHERE schemaname = 'lotbot';
  SELECT string_agg(t.tablename, ', ') INTO sin_lectura
    FROM pg_tables t
   WHERE t.schemaname = 'lotbot'
     AND NOT has_table_privilege('lotbot_copia', format('%I.%I', t.schemaname, t.tablename), 'SELECT');
  IF sin_lectura IS NOT NULL THEN
    RAISE EXCEPTION 'No puede leer estas tablas de lotbot: %', sin_lectura;
  END IF;

  SELECT string_agg(format('%I.%I', t.schemaname, t.tablename), ', ') INTO lee_fuera
    FROM pg_tables t
   WHERE t.schemaname NOT IN ('lotbot', 'pg_catalog', 'information_schema')
     AND has_table_privilege('lotbot_copia', format('%I.%I', t.schemaname, t.tablename), 'SELECT');
  IF lee_fuera IS NOT NULL THEN
    RAISE EXCEPTION 'Podría leer tablas que no son de LOT Bot (permiso dado a PUBLIC en el CRM): %', lee_fuera;
  END IF;

  SELECT string_agg(format('%I.%I', t.schemaname, t.tablename), ', ') INTO escribe
    FROM pg_tables t
   WHERE t.schemaname NOT IN ('pg_catalog', 'information_schema')
     AND has_table_privilege('lotbot_copia', format('%I.%I', t.schemaname, t.tablename),
                             'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER');
  IF escribe IS NOT NULL THEN
    RAISE EXCEPTION 'Podría modificar: %', escribe;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_namespace n
              WHERE n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
                AND has_schema_privilege('lotbot_copia', n.oid, 'CREATE')) THEN
    RAISE EXCEPTION 'Podría crear objetos en algún esquema.';
  END IF;

  RAISE NOTICE 'CORRECTO: lotbot_copia lee las % tablas de lotbot, nada más, y no puede escribir.', total;
END $$;

COMMIT;
