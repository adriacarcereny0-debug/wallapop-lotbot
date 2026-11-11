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

async function ensureSchema(sql: Sql): Promise<void> {
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS settings (
      key text PRIMARY KEY,
      value jsonb NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plans (
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
    CREATE TABLE IF NOT EXISTS payment_methods (
      id text PRIMARY KEY,
      name text NOT NULL,
      enabled boolean NOT NULL DEFAULT false,
      instructions text NOT NULL DEFAULT '',
      sort integer NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS customers (
      id serial PRIMARY KEY,
      email text UNIQUE NOT NULL,
      email_normalized text NOT NULL,
      name text NOT NULL DEFAULT '',
      phone text NOT NULL DEFAULT '',
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS customers_email_norm ON customers (email_normalized);
    CREATE TABLE IF NOT EXISTS licenses (
      id serial PRIMARY KEY,
      key text UNIQUE NOT NULL,
      customer_id integer REFERENCES customers(id) ON DELETE SET NULL,
      kind text NOT NULL CHECK (kind IN ('prueba', 'pago', 'manual')),
      plan_id integer REFERENCES plans(id) ON DELETE SET NULL,
      status text NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'revocada')),
      starts_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz,
      max_devices integer NOT NULL DEFAULT 1,
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS license_devices (
      license_id integer NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
      device_id text NOT NULL,
      first_seen timestamptz NOT NULL DEFAULT now(),
      last_seen timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (license_id, device_id)
    );
    CREATE TABLE IF NOT EXISTS trials (
      id serial PRIMARY KEY,
      email_normalized text UNIQUE NOT NULL,
      ip_hash text NOT NULL,
      device_id text,
      license_id integer REFERENCES licenses(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS trials_ip ON trials (ip_hash, created_at);
    CREATE UNIQUE INDEX IF NOT EXISTS trials_device ON trials (device_id) WHERE device_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS orders (
      id serial PRIMARY KEY,
      reference text UNIQUE NOT NULL,
      customer_id integer REFERENCES customers(id) ON DELETE SET NULL,
      plan_id integer REFERENCES plans(id) ON DELETE SET NULL,
      plan_name text NOT NULL,
      method text NOT NULL,
      amount_cents integer NOT NULL,
      currency text NOT NULL DEFAULT 'EUR',
      status text NOT NULL DEFAULT 'pendiente' CHECK (status IN ('pendiente', 'pagado', 'cancelado')),
      stripe_session_id text,
      license_id integer REFERENCES licenses(id) ON DELETE SET NULL,
      notes text NOT NULL DEFAULT '',
      created_at timestamptz NOT NULL DEFAULT now(),
      paid_at timestamptz
    );
    CREATE TABLE IF NOT EXISTS events (
      id serial PRIMARY KEY,
      at timestamptz NOT NULL DEFAULT now(),
      actor text NOT NULL DEFAULT 'web',
      action text NOT NULL,
      detail text NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS login_attempts (
      ip_hash text NOT NULL,
      at timestamptz NOT NULL DEFAULT now()
    );
  `);
  await seed(sql);
}

/** Datos de partida (solo si las tablas están vacías). Todo se cambia en /admin. */
async function seed(sql: Sql): Promise<void> {
  const [{ count: plans }] = await sql<{ count: number }[]>`SELECT count(*)::int AS count FROM plans`;
  if (plans === 0) {
    const base = [
      "Publicación automática en Wallapop desde tu Anuncio principal",
      "Varias cuentas, cada una con su propio navegador",
      "Fotos distintas en cada anuncio (no se repiten)",
      "Avisos de verificación: tú la completas y LOT Bot sigue",
      "Actualizaciones incluidas",
    ];
    await sql`
      INSERT INTO plans ${sql([
        {
          slug: "mensual", name: "Mensual", description: "Pago mes a mes, sin permanencia.",
          price_cents: 2900, period_label: "mes", duration_days: 30, max_devices: 1,
          features: sql.json(base), highlighted: false, sort: 1,
        },
        {
          slug: "trimestral", name: "Trimestral", description: "Tres meses con descuento.",
          price_cents: 7900, period_label: "3 meses", duration_days: 90, max_devices: 1,
          features: sql.json(base), highlighted: true, sort: 2,
        },
        {
          slug: "anual", name: "Anual", description: "Un año completo al mejor precio.",
          price_cents: 24900, period_label: "año", duration_days: 365, max_devices: 2,
          features: sql.json([...base, "Hasta 2 ordenadores"]), highlighted: false, sort: 3,
        },
      ])}
    `;
    await setSetting(sql, "plans_are_examples", true);
  }
  await sql`
    INSERT INTO payment_methods (id, name, enabled, instructions, sort) VALUES
      ('tarjeta', 'Tarjeta (Stripe)', true, '', 1),
      ('bizum', 'Bizum', false, '', 2),
      ('transferencia', 'Transferencia bancaria', false, '', 3),
      ('paypal', 'PayPal', false, '', 4)
    ON CONFLICT (id) DO NOTHING
  `;
}

export async function getSetting<T>(key: string, fallback: T): Promise<T> {
  const sql = await db();
  const rows = await sql<{ value: T }[]>`SELECT value FROM settings WHERE key = ${key}`;
  return rows.length ? rows[0].value : fallback;
}

export async function setSetting(sqlOrNull: Sql | null, key: string, value: unknown): Promise<void> {
  const sql = sqlOrNull ?? (await db());
  await sql`
    INSERT INTO settings (key, value) VALUES (${key}, ${sql.json(value as never)})
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
  `;
}

export async function logEvent(action: string, detail = "", actor = "web"): Promise<void> {
  const sql = await db();
  await sql`INSERT INTO events (actor, action, detail) VALUES (${actor}, ${action}, ${detail.slice(0, 2000)})`;
}
