# Configurar la copia de seguridad diaria (paso a paso)

Nadie más que tú ve las contraseñas: se escriben en Neon y en GitHub, nunca
en el chat ni en el repositorio.

## Qué se copia

**Solo el esquema `lotbot`**: hoy 17 tablas (las crean las migraciones de
`web/src/lib/db.ts`; 18 creadas y `license_devices` borrada en la 2):
`customers`, `devices`, `events`, `license_connections`, `license_events`,
`licenses`, `login_attempts`, `orders`, `password_tokens`, `payment_methods`,
`plans`, `releases`, `schema_migrations`, `settings`, `stripe_events`,
`subscriptions`, `trials`. El resto de tablas de la base `neondb` (las del
CRM, en otros esquemas) no son de LOT Bot: ni se copian ni se pueden leer
con este usuario. La web no usa ninguna tabla fuera de `lotbot`.

## Si el usuario existe pero «no puede leer ninguna tabla»

Causa más probable (reproducida): la primera versión del script se ejecutó
con **otra base** elegida en el SQL Editor. Los usuarios son comunes a todas
las bases, pero los permisos son de cada base: `CREATE ROLE` funcionó (con
`BYPASSRLS`) y los `GRANT` sobre `lotbot` fallaron porque ahí no existe ese
esquema. La versión actual del script se niega a ejecutarse fuera de
`neondb`, es todo o nada, corrige un usuario ya existente y comprueba el
resultado al final.

Para confirmarlo (solo lectura), en el SQL Editor con **neondb**:

```sql
SELECT current_database(), current_user;
SELECT rolname, rolbypassrls, rolinherit,
       (SELECT string_agg(g.rolname, ', ') FROM pg_auth_members m
          JOIN pg_roles g ON g.oid = m.roleid WHERE m.member = r.oid) AS grupos
  FROM pg_roles r WHERE rolname = 'lotbot_copia';
SELECT t.schemaname, count(*) AS tablas,
       count(*) FILTER (WHERE has_table_privilege('lotbot_copia',
             format('%I.%I', t.schemaname, t.tablename), 'SELECT')) AS legibles
  FROM pg_tables t
 WHERE t.schemaname NOT IN ('pg_catalog', 'information_schema')
 GROUP BY 1 ORDER BY 1;
```

Lo esperado tras el script: `lotbot` → 17 tablas, 17 legibles; cualquier otro
esquema → 0 legibles; `grupos` vacío. Si `grupos` muestra `neon_superuser`,
el usuario se creó desde el panel: bórralo y vuelve a ejecutar el script.

## 1. Usuario de solo lectura en Neon

1. Genera en tu gestor de contraseñas una contraseña **solo con letras y
   números**, de 32 caracteres o más (así no hay que codificar símbolos en la
   dirección de conexión). Guárdala como «Neon lotbot_copia».
2. Neon → proyecto → **SQL Editor** → rama `main` y, en el selector de base
   de datos, **`neondb`**.
3. Pega el contenido de `scripts/sql/usuario_copia.sql`, cambia
   `CAMBIA_ESTA_CONTRASEÑA` por esa contraseña y pulsa **Run**. Debe terminar
   con `CORRECTO: lotbot_copia lee las 17 tablas de lotbot, nada más, y no
   puede escribir.` Cualquier otro mensaje = no se ha cambiado nada; el texto
   dice qué hacer.
   - **No** crees el usuario desde el panel *Roles* de Neon: esos usuarios
     entran en `neon_superuser`, que puede escribir en todas las tablas.

Qué hace (probado en PostgreSQL 18 con los mismos dueños y RLS que Neon):
- puede **leer** todas las tablas de `lotbot` (incluidas las que creen
  migraciones futuras) y nada fuera de `lotbot` (el CRM no se ve);
- **no puede escribir**: `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`,
  desactivar RLS o dar permisos fallan, incluso si desactiva el modo de solo
  lectura de su sesión (son dos protecciones independientes);
- `BYPASSRLS` es necesario: sin él ve 0 filas (las tablas tienen RLS sin
  políticas) y `pg_dump` falla. No da permiso de escritura.

## 2. Dirección de conexión (BACKUP_DATABASE_URL)

Neon → **Connect** → rama `main`, base `neondb`, **sin «Connection pooling»**
(`pg_dump` necesita conexión directa: el host **no** debe contener
`-pooler`). Copia la dirección y cambia el usuario y la contraseña:

```
postgresql://lotbot_copia:TU_CONTRASEÑA@ep-xxxx.REGION.aws.neon.tech/neondb?sslmode=require
```

## 3. Contraseña de cifrado (BACKUP_PASSPHRASE)

Otra contraseña distinta, larga (40+ caracteres). Guárdala en tu gestor como
«Copia LOT Bot – cifrado»: **sin ella las copias no se pueden abrir** y no
hay forma de recuperarla.

## 4. Secretos en GitHub

GitHub → repositorio → **Settings** → **Secrets and variables** → **Actions**
→ **New repository secret**, dos veces:

| Name | Secret |
|---|---|
| `BACKUP_DATABASE_URL` | la dirección del paso 2 |
| `BACKUP_PASSPHRASE` | la contraseña del paso 3 |

## 5. Avisos por email si falla

GitHub → tu foto → **Settings** → **Notifications** → **System** →
**Actions**: activa las notificaciones por email y «Only notify for failed
workflows». Los flujos programados avisan a la persona que hizo el último
cambio en su programación (tu cuenta).

## 6. Comprobaciones (las hace Claude, sin escribir en producción)

- En Neon, solo lectura: que `lotbot_copia` existe, no es superusuario, no
  pertenece a `neon_superuser`, tiene `BYPASSRLS` y **solo** `SELECT` en
  `lotbot`.
- Lanzar «Copia de seguridad» a mano (sin ensayo): copia cifrada → restaurada
  en una base desechable del propio trabajo → mismas filas en cada tabla →
  artefacto de 30 días.
- Descargar el artefacto y comprobar que está cifrado (sin abrirlo: la
  contraseña de cifrado solo la conoces tú).
