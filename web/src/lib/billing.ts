/**
 * Suscripciones con Stripe y su efecto en la licencia.
 *
 * Reglas (las decide Stripe; aquí solo se traducen a la licencia):
 *
 * | Estado en Stripe              | Licencia                                          |
 * |-------------------------------|---------------------------------------------------|
 * | active / trialing             | activa hasta fin del periodo + 5 días de margen   |
 * | past_due (pago fallido)       | igual: sigue hasta fin del periodo + 5 días       |
 * | cancelada al final de periodo | activa hasta fin del periodo (sin margen)         |
 * | canceled / incomplete_expired | termina ya                                        |
 * | unpaid / paused               | suspendida «Impago (Stripe)»                      |
 *
 * Cada cliente conserva SIEMPRE la misma clave: al suscribirse se aprovecha
 * su licencia de prueba o la de una suscripción anterior, así LOT Bot sigue
 * funcionando sin escribir otra clave.
 */
import type Stripe from "stripe";

import { db, logEvent } from "./db";
import { stripe } from "./stripe";
import type { License, Plan } from "./store";
import { newLicenseKey } from "./util";

export const GRACE_DAYS = Number(process.env.BILLING_GRACE_DAYS) || 5;
export const UNPAID_REASON = "Impago (Stripe)";

export function billingConfigured(): boolean {
  return Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);
}

/** Lo que se necesita de una suscripción de Stripe (sirve el objeto del aviso). */
export type SubscriptionLike = {
  id: string;
  status: string;
  customer: string | { id: string };
  cancel_at_period_end: boolean;
  cancel_at?: number | null;
  ended_at?: number | null;
  current_period_end?: number | null;
  metadata?: Record<string, string> | null;
  items?: {
    data: {
      current_period_end?: number | null;
      price?: {
        unit_amount?: number | null;
        currency?: string | null;
        recurring?: { interval?: string | null } | null;
      } | null;
    }[];
  };
};

function customerIdOf(sub: SubscriptionLike): string {
  return typeof sub.customer === "string" ? sub.customer : sub.customer.id;
}

/** Desde la versión 2025 de la API, el fin de periodo va en cada elemento. */
export function periodEnd(sub: SubscriptionLike): number | null {
  const fromItems = sub.items?.data
    ?.map((item) => item.current_period_end ?? 0)
    .filter(Boolean) as number[] | undefined;
  if (fromItems?.length) return Math.max(...fromItems);
  return sub.current_period_end ?? null;
}

/** Fecha hasta la que vale la licencia según la suscripción (null = no se cambia). */
export function licenseEnd(sub: SubscriptionLike, now = Date.now()): { expires: Date | null; suspend: boolean } {
  const end = periodEnd(sub);
  const endMs = end ? end * 1000 : null;
  switch (sub.status) {
    case "active":
    case "trialing":
    case "past_due": {
      if (!endMs) return { expires: null, suspend: false };
      if (sub.cancel_at) return { expires: new Date(Math.min(sub.cancel_at * 1000, endMs)), suspend: false };
      if (sub.cancel_at_period_end) return { expires: new Date(endMs), suspend: false };
      return { expires: new Date(endMs + GRACE_DAYS * 86400 * 1000), suspend: false };
    }
    case "canceled":
    case "incomplete_expired":
      return { expires: new Date(sub.ended_at ? sub.ended_at * 1000 : now), suspend: false };
    case "unpaid":
    case "paused":
      return { expires: null, suspend: true };
    default: // incomplete: aún no ha pagado
      return { expires: null, suspend: false };
  }
}

const LIVE = new Set(["active", "trialing", "past_due"]);

async function planFor(sub: SubscriptionLike): Promise<Plan | null> {
  const sql = await db();
  const slug = sub.metadata?.plan_slug;
  if (slug) {
    const rows = await sql<Plan[]>`SELECT * FROM lotbot.plans WHERE slug = ${slug}`;
    if (rows.length) return rows[0];
  }
  const interval = sub.items?.data?.[0]?.price?.recurring?.interval;
  if (interval === "month" || interval === "year") {
    const rows = await sql<Plan[]>`
      SELECT * FROM lotbot.plans WHERE billing_interval = ${interval} ORDER BY active DESC, sort, id LIMIT 1
    `;
    return rows[0] ?? null;
  }
  return null;
}

/**
 * Aplica el estado de una suscripción a la base de datos y a la licencia.
 * `eventAt` (segundos): los avisos viejos que llegan tarde no pisan a los nuevos.
 */
export async function syncSubscription(sub: SubscriptionLike, eventAt: number): Promise<{ licenseId: number | null; skipped: boolean }> {
  const sql = await db();
  const stripeCustomer = customerIdOf(sub);
  const plan = await planFor(sub);
  const metaCustomer = Number(sub.metadata?.customer_id) || null;
  const price = sub.items?.data?.[0]?.price;
  const end = periodEnd(sub);

  return sql.begin(async (tx) => {
    const [existing] = await tx<{ id: number; license_id: number | null; customer_id: number | null; last_event_at: Date | null }[]>`
      SELECT id, license_id, customer_id, last_event_at FROM lotbot.subscriptions
      WHERE stripe_subscription_id = ${sub.id} FOR UPDATE
    `;
    if (existing?.last_event_at && existing.last_event_at.getTime() > eventAt * 1000) {
      return { licenseId: existing.license_id, skipped: true };
    }

    // ¿De qué cliente es? Primero el que se puso al pagar; si no, por su id de Stripe.
    let customerId = existing?.customer_id ?? null;
    if (!customerId && metaCustomer) {
      const rows = await tx`SELECT 1 FROM lotbot.customers WHERE id = ${metaCustomer}`;
      if (rows.length) customerId = metaCustomer;
    }
    if (!customerId) {
      const rows = await tx<{ id: number }[]>`
        SELECT id FROM lotbot.customers WHERE stripe_customer_id = ${stripeCustomer}
      `;
      customerId = rows[0]?.id ?? null;
    }
    if (customerId) {
      await tx`
        UPDATE lotbot.customers SET stripe_customer_id = ${stripeCustomer}
        WHERE id = ${customerId} AND stripe_customer_id IS NULL
      `;
    }

    // Licencia: la de esta suscripción, o se reaprovecha la del cliente.
    let licenseId = existing?.license_id ?? null;
    if (!licenseId && customerId && LIVE.has(sub.status)) {
      const [reuse] = await tx<{ id: number }[]>`
        SELECT l.id FROM lotbot.licenses l
        WHERE l.customer_id = ${customerId} AND l.status <> 'revocada'
          AND (l.kind = 'prueba' OR NOT EXISTS (
            SELECT 1 FROM lotbot.subscriptions s
            WHERE s.license_id = l.id AND s.status IN ('active', 'trialing', 'past_due')
              AND s.stripe_subscription_id <> ${sub.id}))
          AND l.kind IN ('prueba', 'pago')
        ORDER BY (l.kind = 'pago') DESC, l.id DESC LIMIT 1
      `;
      if (reuse) {
        licenseId = reuse.id;
      } else {
        const [created] = await tx<License[]>`
          INSERT INTO lotbot.licenses (key, customer_id, kind, plan_id, max_devices, notes)
          VALUES (${newLicenseKey()}, ${customerId}, 'pago', ${plan?.id ?? null}, ${plan?.max_devices ?? 1},
                  ${`Suscripción ${sub.id}`})
          RETURNING *
        `;
        licenseId = created.id;
      }
    }

    // Una suscripción vieja (cancelada) no toca la licencia si ya la usa otra en vigor.
    let otherLive = false;
    if (licenseId && !LIVE.has(sub.status)) {
      const rows = await tx`
        SELECT 1 FROM lotbot.subscriptions
        WHERE license_id = ${licenseId} AND stripe_subscription_id <> ${sub.id}
          AND status IN ('active', 'trialing', 'past_due')
      `;
      otherLive = rows.length > 0;
    }

    if (licenseId && !otherLive) {
      const { expires, suspend } = licenseEnd(sub);
      const [license] = await tx<{ key: string; status: string; status_reason: string }[]>`
        SELECT key, status, status_reason FROM lotbot.licenses WHERE id = ${licenseId} FOR UPDATE
      `;
      // Una suspensión o revocación hecha a mano en /admin no la deshace Stripe.
      const manualBlock = license.status === "revocada" || (license.status === "suspendida" && license.status_reason !== UNPAID_REASON);
      const status = manualBlock ? license.status : suspend ? "suspendida" : "activa";
      const reason = manualBlock ? license.status_reason : suspend ? UNPAID_REASON : "";
      await tx`
        UPDATE lotbot.licenses SET
          kind = CASE WHEN kind = 'prueba' AND ${LIVE.has(sub.status)} THEN 'pago' ELSE kind END,
          plan_id = COALESCE(${plan?.id ?? null}, plan_id),
          max_devices = CASE WHEN ${plan?.max_devices ?? null}::int IS NULL THEN max_devices ELSE GREATEST(${plan?.max_devices ?? 1}, 1) END,
          expires_at = CASE WHEN ${expires ? expires.toISOString() : null}::timestamptz IS NULL THEN expires_at ELSE ${expires ? expires.toISOString() : null}::timestamptz END,
          status = ${status},
          status_reason = ${reason},
          updated_at = now()
        WHERE id = ${licenseId}
      `;
    }

    const values = {
      stripe_subscription_id: sub.id,
      stripe_customer_id: stripeCustomer,
      customer_id: customerId,
      license_id: licenseId,
      plan_id: plan?.id ?? null,
      status: sub.status,
      current_period_end: end ? new Date(end * 1000) : null,
      cancel_at: sub.cancel_at ? new Date(sub.cancel_at * 1000) : null,
      cancel_at_period_end: Boolean(sub.cancel_at_period_end),
      ended_at: sub.ended_at ? new Date(sub.ended_at * 1000) : null,
      amount_cents: price?.unit_amount ?? null,
      currency: (price?.currency || "eur").toUpperCase(),
      last_event_at: new Date(eventAt * 1000),
    };
    if (existing) {
      await tx`UPDATE lotbot.subscriptions SET ${tx(values)}, updated_at = now() WHERE id = ${existing.id}`;
    } else {
      await tx`INSERT INTO lotbot.subscriptions ${tx(values)}`;
    }
    await tx`
      INSERT INTO lotbot.events (actor, action, detail)
      VALUES ('stripe', ${`Suscripción ${sub.status}`}, ${`${sub.id}${licenseId ? ` · licencia ${licenseId}` : ""}`})
    `;
    return { licenseId, skipped: false };
  });
}

// ---------------------------------------------------------------------------
// Llamadas a Stripe
// ---------------------------------------------------------------------------
type CustomerRow = { id: number; email: string; name: string; founder: boolean; stripe_customer_id: string | null };

async function ensureStripeCustomer(customer: CustomerRow): Promise<string> {
  if (customer.stripe_customer_id) return customer.stripe_customer_id;
  const created = await stripe().customers.create({
    email: customer.email,
    name: customer.name || undefined,
    metadata: { lotbot_customer_id: String(customer.id) },
  });
  const sql = await db();
  await sql`UPDATE lotbot.customers SET stripe_customer_id = ${created.id} WHERE id = ${customer.id} AND stripe_customer_id IS NULL`;
  const [row] = await sql<{ stripe_customer_id: string }[]>`SELECT stripe_customer_id FROM lotbot.customers WHERE id = ${customer.id}`;
  return row.stripe_customer_id;
}

export function priceFor(plan: Plan, founder: boolean): number {
  return founder && plan.founder_price_cents != null ? plan.founder_price_cents : plan.price_cents;
}

export async function hasLiveSubscription(customerId: number): Promise<boolean> {
  const sql = await db();
  const rows = await sql`
    SELECT 1 FROM lotbot.subscriptions
    WHERE customer_id = ${customerId} AND status IN ('active', 'trialing', 'past_due', 'unpaid', 'incomplete')
  `;
  return rows.length > 0;
}

/** Página de pago de Stripe para suscribirse a un plan. */
export async function createSubscriptionCheckout(customerId: number, plan: Plan, baseUrl: string): Promise<string> {
  if (!plan.billing_interval) throw new Error("Este plan no es una suscripción.");
  const sql = await db();
  const [customer] = await sql<CustomerRow[]>`
    SELECT id, email, name, founder, stripe_customer_id FROM lotbot.customers WHERE id = ${customerId}
  `;
  if (!customer) throw new Error("No existe el cliente.");
  const stripeCustomer = await ensureStripeCustomer(customer);
  const amount = priceFor(plan, customer.founder);
  const session = await stripe().checkout.sessions.create({
    mode: "subscription",
    customer: stripeCustomer,
    client_reference_id: String(customer.id),
    locale: "es",
    allow_promotion_codes: true,
    line_items: [
      {
        quantity: 1,
        price_data: {
          currency: plan.currency.toLowerCase(),
          unit_amount: amount,
          recurring: { interval: plan.billing_interval },
          product_data: {
            name: `LOT Bot · ${plan.name}${customer.founder && amount !== plan.price_cents ? " (fundador)" : ""}`,
            metadata: { plan_slug: plan.slug },
          },
        },
      },
    ],
    subscription_data: { metadata: { customer_id: String(customer.id), plan_slug: plan.slug } },
    metadata: { customer_id: String(customer.id), plan_slug: plan.slug },
    success_url: `${baseUrl}/cuenta/bienvenida?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${baseUrl}/cuenta?pago=cancelado`,
  });
  if (!session.url) throw new Error("Stripe no ha devuelto la página de pago.");
  await logEvent("Pago de suscripción abierto", `${customer.email} · ${plan.name}`, "web");
  return session.url;
}

/** Portal de Stripe: tarjeta, facturas y cancelar. */
export async function createPortal(customerId: number, returnUrl: string): Promise<string> {
  const sql = await db();
  const [customer] = await sql<CustomerRow[]>`
    SELECT id, email, name, founder, stripe_customer_id FROM lotbot.customers WHERE id = ${customerId}
  `;
  if (!customer?.stripe_customer_id) throw new Error("Todavía no tienes ninguna suscripción.");
  const session = await stripe().billingPortal.sessions.create({
    customer: customer.stripe_customer_id,
    return_url: returnUrl,
    locale: "es",
  });
  return session.url;
}

/**
 * Al volver de pagar: se comprueba con Stripe y se aplica ya (sin esperar al
 * aviso). Devuelve el cliente si el pago es de verdad suyo.
 */
export async function fulfillCheckout(sessionId: string): Promise<{ customerId: number; licenseId: number | null } | null> {
  if (!/^cs_[A-Za-z0-9_]+$/.test(sessionId)) return null;
  const session = await stripe().checkout.sessions.retrieve(sessionId, { expand: ["subscription"] });
  if (session.mode !== "subscription" || session.status !== "complete") return null;
  const customerId = Number(session.client_reference_id || session.metadata?.customer_id);
  if (!customerId) return null;
  const subscription = session.subscription as Stripe.Subscription | null;
  if (!subscription || typeof subscription === "string") return { customerId, licenseId: null };
  const result = await syncSubscription(subscription as unknown as SubscriptionLike, Math.floor(Date.now() / 1000));
  return { customerId, licenseId: result.licenseId };
}
