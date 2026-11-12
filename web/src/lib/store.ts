/**
 * Lectura y escritura de los datos de la web: planes, métodos de pago,
 * clientes, pedidos, licencias y pruebas gratis.
 */
import { db, getSetting, logEvent } from "./db";
import { newLicenseKey, newOrderReference, normalizeEmail } from "./util";

export type Plan = {
  id: number;
  slug: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
  period_label: string;
  duration_days: number | null;
  max_devices: number;
  features: string[];
  highlighted: boolean;
  active: boolean;
  sort: number;
};

export type PaymentMethod = {
  id: string;
  name: string;
  enabled: boolean;
  instructions: string;
  sort: number;
};

export type SiteSettings = {
  brand: string;
  whatsapp: string;
  email: string;
  legal_name: string;
  privacy_text: string;
  trial_hours: number;
  trial_enabled: boolean;
};

export const DEFAULT_SETTINGS: SiteSettings = {
  brand: "LOT Bot",
  whatsapp: "",
  email: "",
  legal_name: "",
  privacy_text: "",
  trial_hours: 24,
  trial_enabled: true,
};

export async function siteSettings(): Promise<SiteSettings> {
  const saved = await getSetting<Partial<SiteSettings>>("site", {});
  return { ...DEFAULT_SETTINGS, ...saved };
}

export async function listPlans(onlyActive = true): Promise<Plan[]> {
  const sql = await db();
  return onlyActive
    ? sql<Plan[]>`SELECT * FROM plans WHERE active ORDER BY sort, id`
    : sql<Plan[]>`SELECT * FROM plans ORDER BY sort, id`;
}

export async function getPlan(slug: string): Promise<Plan | null> {
  const sql = await db();
  const rows = await sql<Plan[]>`SELECT * FROM plans WHERE slug = ${slug} AND active`;
  return rows[0] ?? null;
}

export function stripeConfigured(): boolean {
  return Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);
}

/** Métodos que ve el cliente: activados y listos (la tarjeta, con Stripe configurado). */
export async function publicPaymentMethods(): Promise<PaymentMethod[]> {
  const sql = await db();
  const rows = await sql<PaymentMethod[]>`SELECT * FROM payment_methods WHERE enabled ORDER BY sort`;
  return rows.filter((m) => (m.id === "tarjeta" ? stripeConfigured() : m.instructions.trim() !== ""));
}

export async function allPaymentMethods(): Promise<PaymentMethod[]> {
  const sql = await db();
  return sql<PaymentMethod[]>`SELECT * FROM payment_methods ORDER BY sort`;
}

export async function upsertCustomer(email: string, name = "", phone = ""): Promise<number> {
  const sql = await db();
  const rows = await sql<{ id: number }[]>`
    INSERT INTO customers (email, email_normalized, name, phone)
    VALUES (${email}, ${normalizeEmail(email)}, ${name}, ${phone})
    ON CONFLICT (email) DO UPDATE SET
      name = CASE WHEN EXCLUDED.name <> '' THEN EXCLUDED.name ELSE customers.name END,
      phone = CASE WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone ELSE customers.phone END
    RETURNING id
  `;
  return rows[0].id;
}

// ---------------------------------------------------------------------------
// Licencias
// ---------------------------------------------------------------------------
export type License = {
  id: number;
  key: string;
  customer_id: number | null;
  kind: "prueba" | "pago" | "manual";
  plan_id: number | null;
  status: "activa" | "suspendida" | "revocada";
  starts_at: Date;
  expires_at: Date | null;
  max_devices: number;
  notes: string;
  created_at: Date;
};

export async function issueLicense(options: {
  customerId: number | null;
  kind: License["kind"];
  planId?: number | null;
  durationDays?: number | null;
  durationHours?: number | null;
  maxDevices?: number;
  notes?: string;
}): Promise<License> {
  const sql = await db();
  const hours =
    options.durationHours ?? (options.durationDays != null ? options.durationDays * 24 : null);
  for (let attempt = 0; attempt < 5; attempt++) {
    const key = newLicenseKey();
    const rows = await sql<License[]>`
      INSERT INTO licenses (key, customer_id, kind, plan_id, expires_at, max_devices, notes)
      VALUES (
        ${key}, ${options.customerId}, ${options.kind}, ${options.planId ?? null},
        ${hours == null ? null : sql`now() + make_interval(hours => ${hours})`},
        ${options.maxDevices ?? 1}, ${options.notes ?? ""}
      )
      ON CONFLICT (key) DO NOTHING
      RETURNING *
    `;
    if (rows.length) return rows[0];
  }
  throw new Error("No se ha podido crear la clave de licencia.");
}

export type VerifyResult = {
  valid: boolean;
  reason?: string;
  kind?: string;
  plan?: string | null;
  expiresAt?: string | null;
};

/**
 * Comprobación sencilla (versión antigua de la API, sin pase firmado). Usa
 * las mismas reglas que /api/v1: estado, caducidad y ordenadores.
 */
export async function verifyLicense(key: string, deviceId: string): Promise<VerifyResult> {
  const sql = await db();
  const rows = await sql<(License & { plan_name: string | null; status_reason: string })[]>`
    SELECT l.*, p.name AS plan_name FROM licenses l
    LEFT JOIN plans p ON p.id = l.plan_id
    WHERE l.key = ${key.trim().toUpperCase()}
  `;
  const license = rows[0];
  if (!license) return { valid: false, reason: "La clave no existe." };
  const base = {
    kind: license.kind,
    plan: license.plan_name,
    expiresAt: license.expires_at ? new Date(license.expires_at).toISOString() : null,
  };
  if (license.status === "revocada") return { ...base, valid: false, reason: "Licencia revocada." };
  if (license.status === "suspendida") return { ...base, valid: false, reason: "Licencia suspendida." };
  if (license.expires_at && new Date(license.expires_at) < new Date()) {
    return { ...base, valid: false, reason: license.kind === "prueba" ? "La prueba gratis ha terminado." : "La licencia ha caducado." };
  }
  if (deviceId) {
    const [device] = await sql<{ status: string }[]>`
      SELECT status FROM devices WHERE license_id = ${license.id} AND fingerprint = ${deviceId}
    `;
    if (device?.status === "bloqueado") return { ...base, valid: false, reason: "Ordenador bloqueado." };
    if (device?.status === "activo") {
      await sql`UPDATE devices SET last_seen = now() WHERE license_id = ${license.id} AND fingerprint = ${deviceId}`;
    } else {
      const [{ count }] = await sql<{ count: number }[]>`
        SELECT count(*)::int AS count FROM devices WHERE license_id = ${license.id} AND status = 'activo'
      `;
      if (count >= license.max_devices) {
        return { ...base, valid: false, reason: `Esta licencia ya se usa en ${count} ordenador(es) (máximo ${license.max_devices}).` };
      }
      await sql`
        INSERT INTO devices (license_id, fingerprint) VALUES (${license.id}, ${deviceId})
        ON CONFLICT (license_id, fingerprint) DO UPDATE SET status = 'activo', last_seen = now()
      `;
    }
  }
  return { ...base, valid: true };
}

// ---------------------------------------------------------------------------
// Prueba gratis (un solo uso)
// ---------------------------------------------------------------------------
export type TrialOutcome =
  | { ok: true; key: string; expiresAt: string; hours: number }
  | { ok: false; error: string };

/** Pruebas desde la misma conexión en 30 días (familias/oficinas: 2). */
export const TRIALS_PER_IP = 2;

export async function startTrial(input: {
  email: string;
  name: string;
  phone: string;
  ipHash: string;
  deviceId?: string | null;
}): Promise<TrialOutcome> {
  const settings = await siteSettings();
  if (!settings.trial_enabled) return { ok: false, error: "La prueba gratis no está disponible ahora mismo." };
  const sql = await db();
  const normalized = normalizeEmail(input.email);
  const used = await sql`SELECT 1 FROM trials WHERE email_normalized = ${normalized}`;
  if (used.length) {
    return { ok: false, error: "Este email ya ha usado su prueba gratis (es de un solo uso). Si quieres seguir, elige un plan." };
  }
  if (input.deviceId) {
    const device = await sql`SELECT 1 FROM trials WHERE device_id = ${input.deviceId}`;
    if (device.length) return { ok: false, error: "Este ordenador ya ha usado la prueba gratis." };
  }
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM trials
    WHERE ip_hash = ${input.ipHash} AND created_at > now() - interval '30 days'
  `;
  if (count >= TRIALS_PER_IP) {
    return { ok: false, error: "Desde esta conexión ya se han pedido pruebas gratis. Escríbenos si necesitas ayuda." };
  }
  const customerId = await upsertCustomer(input.email, input.name, input.phone);
  const hours = Math.max(1, Math.min(168, Number(settings.trial_hours) || 24));
  const license = await issueLicense({ customerId, kind: "prueba", durationHours: hours, notes: "Prueba gratis" });
  try {
    await sql`
      INSERT INTO trials (email_normalized, ip_hash, device_id, license_id)
      VALUES (${normalized}, ${input.ipHash}, ${input.deviceId ?? null}, ${license.id})
    `;
  } catch {
    // Dos peticiones a la vez con el mismo email: solo vale la primera.
    await sql`DELETE FROM licenses WHERE id = ${license.id}`;
    return { ok: false, error: "Este email ya ha usado su prueba gratis (es de un solo uso)." };
  }
  await logEvent("Prueba gratis", `${input.email} → ${license.key}`);
  return {
    ok: true,
    key: license.key,
    expiresAt: new Date(license.expires_at as Date).toISOString(),
    hours,
  };
}

// ---------------------------------------------------------------------------
// Pedidos
// ---------------------------------------------------------------------------
export type Order = {
  id: number;
  reference: string;
  customer_id: number | null;
  plan_id: number | null;
  plan_name: string;
  method: string;
  amount_cents: number;
  currency: string;
  status: "pendiente" | "pagado" | "cancelado";
  stripe_session_id: string | null;
  license_id: number | null;
  notes: string;
  created_at: Date;
  paid_at: Date | null;
};

export async function createOrder(input: {
  plan: Plan;
  method: string;
  email: string;
  name: string;
  phone: string;
}): Promise<Order> {
  const sql = await db();
  const customerId = await upsertCustomer(input.email, input.name, input.phone);
  for (let attempt = 0; attempt < 5; attempt++) {
    const rows = await sql<Order[]>`
      INSERT INTO orders (reference, customer_id, plan_id, plan_name, method, amount_cents, currency)
      VALUES (${newOrderReference()}, ${customerId}, ${input.plan.id}, ${input.plan.name},
              ${input.method}, ${input.plan.price_cents}, ${input.plan.currency})
      ON CONFLICT (reference) DO NOTHING
      RETURNING *
    `;
    if (rows.length) {
      await logEvent("Pedido nuevo", `${rows[0].reference} · ${input.plan.name} · ${input.method} · ${input.email}`);
      return rows[0];
    }
  }
  throw new Error("No se ha podido crear el pedido.");
}

export async function getOrder(reference: string) {
  const sql = await db();
  const rows = await sql<(Order & { license_key: string | null; license_expires: Date | null; email: string | null })[]>`
    SELECT o.*, l.key AS license_key, l.expires_at AS license_expires, c.email
    FROM orders o
    LEFT JOIN licenses l ON l.id = o.license_id
    LEFT JOIN customers c ON c.id = o.customer_id
    WHERE o.reference = ${reference}
  `;
  return rows[0] ?? null;
}

/**
 * Marca un pedido como pagado y crea su licencia (una sola vez, aunque se
 * llame dos veces: botón en /admin y aviso de Stripe).
 */
export async function markOrderPaid(orderId: number, actor: string): Promise<Order> {
  const sql = await db();
  return sql.begin(async (tx) => {
    const [order] = await tx<Order[]>`SELECT * FROM orders WHERE id = ${orderId} FOR UPDATE`;
    if (!order) throw new Error("No existe el pedido.");
    if (order.status === "pagado" && order.license_id) return order;
    const [plan] = await tx<Plan[]>`SELECT * FROM plans WHERE id = ${order.plan_id}`;
    const days = plan?.duration_days ?? null;
    const [license] = await tx<License[]>`
      INSERT INTO licenses (key, customer_id, kind, plan_id, expires_at, max_devices, notes)
      VALUES (${newLicenseKey()}, ${order.customer_id}, 'pago', ${order.plan_id},
              ${days == null ? null : tx`now() + make_interval(days => ${days})`},
              ${plan?.max_devices ?? 1}, ${`Pedido ${order.reference}`})
      RETURNING *
    `;
    const [updated] = await tx<Order[]>`
      UPDATE orders SET status = 'pagado', paid_at = now(), license_id = ${license.id}
      WHERE id = ${order.id} RETURNING *
    `;
    await tx`INSERT INTO events (actor, action, detail) VALUES (${actor}, 'Pedido pagado', ${`${order.reference} → ${license.key}`})`;
    return updated;
  });
}

export async function plansAreExamples(): Promise<boolean> {
  return getSetting<boolean>("plans_are_examples", false);
}
