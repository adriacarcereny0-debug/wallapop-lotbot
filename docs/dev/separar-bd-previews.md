# Separar la base de datos de las vistas previas de la de producción

Estado: **plan, sin aplicar**. Requiere tu autorización (cambia la
configuración de Vercel y de Neon).

## El problema (comprobado el 14/11/2026)

- En Vercel, las variables de la base de datos (`DATABASE_URL`,
  `POSTGRES_URL`, `PGHOST`…) las gestiona la integración de Neon y están
  marcadas para **Preview y Production** a la vez.
- Neon (proyecto `patient-salad-91083309`) tiene **una sola rama**, `main`,
  que Neon marca como «vercel production branch».
- Por tanto, **cada vista previa** (cualquier rama empujada a GitHub) se
  conecta a los datos reales y, al primer acceso, **aplica sus migraciones
  nuevas a producción** (ver `web/src/lib/db.ts`). Si alguien usa sus
  formularios (`/prueba`, `/comprar`), también crea clientes, pruebas y
  pedidos reales.
- Esa base la comparte además el CRM (esquema distinto); una migración
  equivocada en una vista previa podría afectarle.
- Mitigación parcial actual: las vistas previas no tienen `ADMIN_PASSWORD`,
  `SESSION_SECRET` ni `LICENSE_SIGNING_KEY`, así que no hay admin, cuentas de
  cliente ni firma de licencias.

## Opción recomendada: una rama fija de Neon para *Preview*, sin datos reales

1. **Neon** → proyecto → *Branches* → crear la rama `preview` desde `main`
   eligiendo **solo esquema** (sin datos), si la opción está disponible en tu
   plan; si no, crearla y vaciar después las tablas de `lotbot` con datos
   personales (clientes, licencias, pedidos, pruebas, dispositivos, eventos).
   Así ninguna vista previa ve datos de clientes.
2. **Neon** → rama `preview` → *Roles*: crear un rol propio
   (`lotbot_preview`) con permisos solo en esa rama.
3. **Vercel** → proyecto `web` → *Settings* → *Environment Variables*:
   - quitar **Preview** de las variables de la integración de Neon (que
     queden solo en *Production*); como son de la integración, puede que haya
     que hacerlo desde *Storage* → la base de Neon → ajustes de entornos;
   - añadir `DATABASE_URL` **solo para Preview** con la conexión de la rama
     `preview` (con su rol propio).
4. Redesplegar una vista previa cualquiera y comprobar `/api/health`: debe
   decir `"ok":true` y, en la base `preview`, verse la conexión (no en
   `main`).
5. Comprobar en `main` (solo lectura) que `lotbot.schema_migrations` no ha
   cambiado.

Ventajas: simple, sin datos personales en vistas previas, y una migración
nueva se prueba primero en `preview`. Inconveniente: hay que mantener la rama
`preview` (por ejemplo, rehacerla desde `main` en solo esquema cada cierto
tiempo).

## Alternativa: una rama de Neon por cada vista previa

La integración Neon–Vercel puede crear una rama de base de datos por cada
despliegue de vista previa. Aísla cada rama de código, pero **copia los datos
de producción** (datos personales de clientes) en cada una y crea muchas
ramas que hay que limpiar. Solo la recomendaría si se añade un paso que
borre los datos personales.

## Protección adicional en el código (propuesta, no aplicada)

Para que un error de configuración no pueda repetir el problema: en
`ensureSchema()`, si `VERCEL_ENV === "preview"` y faltan migraciones por
aplicar, **no aplicarlas** salvo que exista `LOTBOT_PREVIEW_MIGRATIONS=1`
(que solo se pondría en la base `preview`). Necesita pruebas propias; se
haría en una rama aparte.

## Qué NO cambia

- Producción (`www.lotbot.es`) sigue con `main` igual que hoy.
- La copia de seguridad (`BACKUP_DATABASE_URL`) debe apuntar a `main`.
