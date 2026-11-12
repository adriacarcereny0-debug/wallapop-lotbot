/**
 * Base de datos (Postgres). En Vercel: Storage → Neon, que rellena DATABASE_URL.
 *
 * Las tablas se crean solas la primera vez (no hay que ejecutar nada a mano)
 * y se rellenan con unos planes y métodos de pago de partida, que se cambian
 * desde /admin.
 */
import postgres from "postgres";

type Sql = ReturnType<typeof postgres>;

const globalForDb = globalThis as unknown as { lotbotSql?: Sql; lotbotSchema?: Promise<void> };

export function databaseUrl(): string | undefined {
  return (
    process.env.DATABASE_URL ||
    process.env.POSTGRES_URL ||
    process.env.DATABASE_URL_UNPOOLED ||
    undefined
  );
}

export function hasDatabase(): boolean {
  return Boolean(databaseUrl());
}

function client(): Sql {
  const url = databaseUrl();
  if (!url) {
    throw new Error("Falta DATABASE_URL: conecta una base de datos Postgres (Vercel → Storage).");
  }
  if (!globalForDb.lotbotSql) {
    const local = /@(localhost|127\.0\.0\.1)[:/]/.test(url);
    globalForDb.lotbotSql = postgres(url, {
      max: 3,
      idle_timeout: 20,
      prepare: false, // compatible con el «pooler» de Neon / PgBouncer
      ssl: local ? false : "require",
      onnotice: () => {},
    });
  }
  return globalForDb.lotbotSql;
}

/** Cliente listo para usar (con las tablas creadas). */
export async function db(): Promise<Sql> {
  const sql = client();
  if (!globalForDb.lotbotSchema) {
    globalForDb.lotbotSchema = ensureSchema(sql).catch((error) => {
      globalForDb.lotbotSchema = undefined;
      throw error;
    });
  }
  await globalForDb.lotbotSchema;
  return sql;
}

/**
 * Todas las tablas de LOT Bot viven en el esquema «lotbot» (nunca en
 * «public»): la base de datos puede compartirse con otras aplicaciones sin
 * que choquen nombres como «settings», «customers» o «schema_migrations».
 *
 * Migraciones numeradas: cada una se aplica UNA vez, en orden, dentro de una
 * transacción y con un bloqueo (dos servidores arrancando a la vez no
 * migran dos veces). Para cambiar el esquema: añadir una nueva al final.
 */
const MIGRATIONS: { version: number; name: string; sql: string }[] = [
  { version: 1, name: "esquema inicial", sql: `
    CREATE TABLE IF NOT EXISTS lotbot.settings (
      key text PRIMARY KEY,
      value jsonb NOT NULL
    );
    CREATE TABLE IF NOT EXISTS lotbot.plans (
      id serial PRIMARY KEY,
      slug text UNIQUE NOT NULL,
      name text NOT NULL,
      description text NOT NULL DEFAULT '',
      price_cents integer NOT NULL CHECK (price_cents >= 0),
      currency text NOT NULL DEFAULT 'EUR',
      period_label text NOT NULL DEFAULT 'mes',
      duration_days integer,
      max_devices integer NOT NULL DEFAULT 1,
      features jsonb NOT NULL DEFAULT '[]',
      highlighted boolean NOT NULL DEFAULT false,
      active boolean NOT NULL DEFAULT true,
      sort integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS lotbot.payment_methods (
      id text PRIMARY KEY,
      name text NOT NULL,
      enabled boolean NOT NULL DEFAULT false,
      instructions text NOT NULL DEFAULT '',
      sort integer NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS lotbot.customers (
      id serial PRIMARY KEY,
      email text UNIQUE NOT NULL,
      email_normalized text NOT NULL,
      name text NOT NULL DEFAULT '',
      phone text NOT NULL DEFAULT '',
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS customers_email_norm ON lotbot.customers (email_normalized);
    CREATE TABLE IF NOT EXISTS lotbot.licenses (
      id serial PRIMARY KEY,
      key text UNIQUE NOT NULL,
      customer_id integer REFERENCES lotbot.customers(id) ON DELETE SET NULL,
      kind text NOT NULL CHECK (kind IN ('prueba', 'pago', 'manual')),
      plan_id integer REFERENCES lotbot.plans(id) ON DELETE SET NULL,
      status text NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'revocada')),
      starts_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz,
      max_devices integer NOT NULL DEFAULT 1,
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS lotbot.license_devices (
      license_id integer NOT NULL REFERENCES lotbot.licenses(id) ON DELETE CASCADE,
      device_id text NOT NULL,
      first_seen timestamptz NOT NULL DEFAULT now(),
      last_seen timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (license_id, device_id)
    );
    CREATE TABLE IF NOT EXISTS lotbot.trials (
      id serial PRIMARY KEY,
      email_normalized text UNIQUE NOT NULL,
      ip_hash text NOT NULL,
      device_id text,
      license_id integer REFERENCES lotbot.licenses(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS trials_ip ON lotbot.trials (ip_hash, created_at);
    CREATE UNIQUE INDEX IF NOT EXISTS trials_device ON lotbot.trials (device_id) WHERE device_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS lotbot.orders (
      id serial PRIMARY KEY,
      reference text UNIQUE NOT NULL,
      customer_id integer REFERENCES lotbot.customers(id) ON DELETE SET NULL,
      plan_id integer REFERENCES lotbot.plans(id) ON DELETE SET NULL,
      plan_name text NOT NULL,
      method text NOT NULL,
      amount_cents integer NOT NULL,
      currency text NOT NULL DEFAULT 'EUR',
      status text NOT NULL DEFAULT 'pendiente' CHECK (status IN ('pendiente', 'pagado', 'cancelado')),
      stripe_session_id text,
      license_id integer REFERENCES lotbot.licenses(id) ON DELETE SET NULL,
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now(),
      paid_at timestamptz
    );
    CREATE TABLE IF NOT EXISTS lotbot.events (
      id serial PRIMARY KEY,
      at timestamptz NOT NULL DEFAULT now(),
      actor text NOT NULL DEFAULT 'web',
      action text NOT NULL,
      detail text NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS lotbot.login_attempts (
      ip_hash text NOT NULL,
      at timestamptz NOT NULL DEFAULT now()
    );
  ` },
  {
    version: 2,
    name: "licencias v2: dispositivos, estados, actividad y RLS",
    sql: `
    ALTER TABLE lotbot.licenses DROP CONSTRAINT IF EXISTS licenses_status_check;
    ALTER TABLE lotbot.licenses ADD CONSTRAINT licenses_status_check
      CHECK (status IN ('activa', 'suspendida', 'revocada'));
    ALTER TABLE lotbot.licenses ADD COLUMN IF NOT EXISTS status_reason text NOT NULL DEFAULT '';
    ALTER TABLE lotbot.licenses ADD COLUMN IF NOT EXISTS user_id uuid;
    ALTER TABLE lotbot.licenses ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
    CREATE INDEX IF NOT EXISTS licenses_customer ON lotbot.licenses (customer_id);

    CREATE TABLE IF NOT EXISTS lotbot.devices (
      id serial PRIMARY KEY,
      license_id integer NOT NULL REFERENCES lotbot.licenses(id) ON DELETE CASCADE,
      fingerprint text NOT NULL,
      name text NOT NULL DEFAULT '',
      os text NOT NULL DEFAULT '',
      app_version text NOT NULL DEFAULT '',
      status text NOT NULL DEFAULT 'activo' CHECK (status IN ('activo', 'desvinculado', 'bloqueado')),
      first_seen timestamptz NOT NULL DEFAULT now(),
      last_seen timestamptz NOT NULL DEFAULT now(),
      last_ip_hash text NOT NULL DEFAULT '',
      UNIQUE (license_id, fingerprint)
    );
    CREATE INDEX IF NOT EXISTS devices_fingerprint ON lotbot.devices (fingerprint);
    INSERT INTO lotbot.devices (license_id, fingerprint, first_seen, last_seen)
      SELECT license_id, device_id, first_seen, last_seen FROM lotbot.license_devices
      ON CONFLICT DO NOTHING;
    DROP TABLE IF EXISTS lotbot.license_devices;

    CREATE TABLE IF NOT EXISTS lotbot.license_events (
      id bigserial PRIMARY KEY,
      at timestamptz NOT NULL DEFAULT now(),
      license_id integer REFERENCES lotbot.licenses(id) ON DELETE CASCADE,
      kind text NOT NULL,
      fingerprint text NOT NULL DEFAULT '',
      ip_hash text NOT NULL DEFAULT '',
      detail text NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS license_events_license ON lotbot.license_events (license_id, at);
    CREATE INDEX IF NOT EXISTS license_events_ip ON lotbot.license_events (ip_hash, kind, at);

    -- Todo va en el esquema propio «lotbot» (no choca con otras aplicaciones
    -- de la misma base de datos y Supabase no lo publica por su API). Además,
    -- RLS activado y sin políticas: nadie puede leerlas desde fuera. Este
    -- servidor se conecta con el usuario propietario y no se ve afectado.
    ALTER TABLE lotbot.settings ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.payment_methods ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.customers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.licenses ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.devices ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.trials ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.orders ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.login_attempts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.license_events ENABLE ROW LEVEL SECURITY;
    `,
  },
  {
    version: 3,
    name: "suscripciones de Stripe y cuentas de cliente",
    sql: `
    -- Cuenta de cliente (/cuenta): contraseña (scrypt), sesiones que se
    -- pueden cerrar todas a la vez y cliente de Stripe.
    ALTER TABLE lotbot.customers ADD COLUMN IF NOT EXISTS password_hash text;
    ALTER TABLE lotbot.customers ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 1;
    ALTER TABLE lotbot.customers ADD COLUMN IF NOT EXISTS stripe_customer_id text;
    ALTER TABLE lotbot.customers ADD COLUMN IF NOT EXISTS founder boolean NOT NULL DEFAULT false;
    CREATE UNIQUE INDEX IF NOT EXISTS customers_stripe ON lotbot.customers (stripe_customer_id)
      WHERE stripe_customer_id IS NOT NULL;

    -- Planes: cada cuánto se cobra y precio de fundador (clientes de antes).
    ALTER TABLE lotbot.plans ADD COLUMN IF NOT EXISTS billing_interval text;
    ALTER TABLE lotbot.plans DROP CONSTRAINT IF EXISTS plans_billing_interval_check;
    ALTER TABLE lotbot.plans ADD CONSTRAINT plans_billing_interval_check
      CHECK (billing_interval IS NULL OR billing_interval IN ('month', 'year'));
    ALTER TABLE lotbot.plans ADD COLUMN IF NOT EXISTS founder_price_cents integer;
    ALTER TABLE lotbot.plans DROP CONSTRAINT IF EXISTS plans_founder_price_check;
    ALTER TABLE lotbot.plans ADD CONSTRAINT plans_founder_price_check
      CHECK (founder_price_cents IS NULL OR founder_price_cents >= 0);
    UPDATE lotbot.plans SET billing_interval = CASE
        WHEN slug = 'anual' OR lower(period_label) IN ('año', 'ano', 'year') THEN 'year'
        WHEN slug = 'mensual' OR lower(period_label) IN ('mes', 'month') THEN 'month'
      END
      WHERE billing_interval IS NULL;

    -- Intentos de entrada: los de /admin y los de /cuenta se cuentan aparte.
    ALTER TABLE lotbot.login_attempts ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'admin';

    CREATE TABLE IF NOT EXISTS lotbot.subscriptions (
      id serial PRIMARY KEY,
      stripe_subscription_id text UNIQUE NOT NULL,
      stripe_customer_id text NOT NULL DEFAULT '',
      customer_id integer REFERENCES lotbot.customers(id) ON DELETE SET NULL,
      license_id integer REFERENCES lotbot.licenses(id) ON DELETE SET NULL,
      plan_id integer REFERENCES lotbot.plans(id) ON DELETE SET NULL,
      status text NOT NULL,
      current_period_end timestamptz,
      cancel_at timestamptz,
      cancel_at_period_end boolean NOT NULL DEFAULT false,
      ended_at timestamptz,
      amount_cents integer,
      currency text NOT NULL DEFAULT 'EUR',
      last_event_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS subscriptions_customer ON lotbot.subscriptions (customer_id);
    CREATE INDEX IF NOT EXISTS subscriptions_license ON lotbot.subscriptions (license_id);

    -- Avisos de Stripe ya procesados (Stripe puede repetirlos).
    CREATE TABLE IF NOT EXISTS lotbot.stripe_events (
      id text PRIMARY KEY,
      type text NOT NULL,
      received_at timestamptz NOT NULL DEFAULT now()
    );

    -- Enlaces de un solo uso para poner o cambiar la contraseña.
    CREATE TABLE IF NOT EXISTS lotbot.password_tokens (
      token_hash text PRIMARY KEY,
      customer_id integer NOT NULL REFERENCES lotbot.customers(id) ON DELETE CASCADE,
      expires_at timestamptz NOT NULL,
      used_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE lotbot.subscriptions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.stripe_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE lotbot.password_tokens ENABLE ROW LEVEL SECURITY;
    `,
  },
  {
    version: 4,
    name: "versiones del programa y actualizaciones",
    sql: `
    -- Cada fila = un instalador de una versión para una plataforma.
    CREATE TABLE IF NOT EXISTS lotbot.releases (
      id serial PRIMARY KEY,
      version text NOT NULL,
      version_sort integer[] NOT NULL,
      platform text NOT NULL CHECK (platform IN ('windows-x64', 'mac-arm64', 'mac-intel')),
      channel text NOT NULL DEFAULT 'estable' CHECK (channel IN ('estable', 'beta')),
      asset_name text NOT NULL,
      github_asset_id bigint,
      download_url text NOT NULL DEFAULT '',
      sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      size bigint NOT NULL CHECK (size > 0),
      notes text NOT NULL DEFAULT '',
      rollout_percent integer NOT NULL DEFAULT 100 CHECK (rollout_percent BETWEEN 0 AND 100),
      mandatory boolean NOT NULL DEFAULT false,
      status text NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'retirada')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (version, platform, channel)
    );
    CREATE INDEX IF NOT EXISTS releases_lookup ON lotbot.releases (platform, channel, status, version_sort);
    ALTER TABLE lotbot.releases ENABLE ROW LEVEL SECURITY;
    `,
  },
  {
    version: 5,
    name: "conexiones por licencia (detectar licencias compartidas)",
    sql: `
    CREATE TABLE IF NOT EXISTS lotbot.license_connections (
      license_id integer NOT NULL REFERENCES lotbot.licenses(id) ON DELETE CASCADE,
      ip_hash text NOT NULL,
      day date NOT NULL,
      checks integer NOT NULL DEFAULT 1,
      PRIMARY KEY (license_id, ip_hash, day)
    );
    CREATE INDEX IF NOT EXISTS license_connections_day ON lotbot.license_connections (day);
    ALTER TABLE lotbot.license_connections ENABLE ROW LEVEL SECURITY;
    `,
  },
];

/** Número de bloqueo para las migraciones (cualquiera fijo). */
const MIGRATION_LOCK = 7_147_656_764;

async function ensureSchema(sql: Sql): Promise<void> {
  await sql.begin(async (tx) => {
    await tx`SELECT pg_advisory_xact_lock(${MIGRATION_LOCK})`;
    await tx.unsafe(`
      CREATE SCHEMA IF NOT EXISTS lotbot;
      CREATE TABLE IF NOT EXISTS lotbot.schema_migrations (
        version integer PRIMARY KEY,
        name text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
      );
      ALTER TABLE lotbot.schema_migrations ENABLE ROW LEVEL SECURITY;
    `);
    const done = new Set(
      (await tx<{ version: number }[]>`SELECT version FROM lotbot.schema_migrations`).map((r) => r.version),
    );
    for (const migration of MIGRATIONS) {
      if (done.has(migration.version)) continue;
      await tx.unsafe(migration.sql);
      await tx`INSERT INTO lotbot.schema_migrations (version, name) VALUES (${migration.version}, ${migration.name})`;
    }
  });
  await seed(sql);
}

export const SCHEMA_VERSION = MIGRATIONS[MIGRATIONS.length - 1].version;

/** Datos de partida (solo si las tablas están vacías). Todo se cambia en /admin. */
async function seed(sql: Sql): Promise<void> {
  const [{ count: plans }] = await sql<{ count: number }[]>`SELECT count(*)::int AS count FROM lotbot.plans`;
  if (plans === 0) {
    const base = [
      "Publicación automática en Wallapop desde tu Anuncio principal",
      "Varias cuentas, cada una con su propio navegador",
      "Fotos distintas en cada anuncio (no se repiten)",
      "Avisos de verificación: tú la completas y LOT Bot sigue",
      "Actualizaciones incluidas",
    ];
    await sql`
      INSERT INTO lotbot.plans ${sql([
        {
          slug: "mensual", name: "Mensual", description: "Suscripción mes a mes, sin permanencia.",
          price_cents: 2900, period_label: "mes", duration_days: 30, max_devices: 1, billing_interval: "month",
          features: sql.json([...base, "1 ordenador"]), highlighted: false, sort: 1,
        },
        {
          slug: "anual", name: "Anual", description: "Un año completo al mejor precio.",
          price_cents: 24900, period_label: "año", duration_days: 365, max_devices: 2, billing_interval: "year",
          features: sql.json([...base, "Hasta 2 ordenadores"]), highlighted: true, sort: 2,
        },
      ])}
    `;
    await setSetting(sql, "plans_are_examples", true);
  }
  await sql`
    INSERT INTO lotbot.payment_methods (id, name, enabled, instructions, sort) VALUES
      ('tarjeta', 'Tarjeta (Stripe)', true, '', 1),
      ('bizum', 'Bizum', false, '', 2),
      ('transferencia', 'Transferencia bancaria', false, '', 3),
      ('paypal', 'PayPal', false, '', 4)
    ON CONFLICT (id) DO NOTHING
  `;
}

export async function getSetting<T>(key: string, fallback: T): Promise<T> {
  const sql = await db();
  const rows = await sql<{ value: T }[]>`SELECT value FROM lotbot.settings WHERE key = ${key}`;
  return rows.length ? rows[0].value : fallback;
}

export async function setSetting(sqlOrNull: Sql | null, key: string, value: unknown): Promise<void> {
  const sql = sqlOrNull ?? (await db());
  await sql`
    INSERT INTO lotbot.settings (key, value) VALUES (${key}, ${sql.json(value as never)})
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
  `;
}

export async function logEvent(action: string, detail = "", actor = "web"): Promise<void> {
  const sql = await db();
  await sql`INSERT INTO lotbot.events (actor, action, detail) VALUES (${actor}, ${action}, ${detail.slice(0, 2000)})`;
}
