/**
 * Suscripciones de Stripe → licencia. Se mandan al webhook avisos FIRMADOS
 * igual que los manda Stripe (con STRIPE_WEBHOOK_SECRET de pruebas) y se
 * comprueba la licencia en la base de datos y con la API v1 de LOT Bot.
 *
 *   El servidor debe arrancar con STRIPE_WEBHOOK_SECRET=whsec_pruebas_lotbot
 *   (y STRIPE_SECRET_KEY=sk_test_falsa para probar /api/checkout sin red).
 *   BASE_URL=http://localhost:3100 DATABASE_URL=postgres://... npm test
 */
import assert from "node:assert/strict";
import { createHmac, randomInt, randomUUID } from "node:crypto";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const SECRET = process.env.STRIPE_WEBHOOK_SECRET ?? "whsec_pruebas_lotbot";
const sql = postgres(process.env.DATABASE_URL, { max: 2, onnotice: () => {} });
const DAY = 86400;
const now = () => Math.floor(Date.now() / 1000);
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const block = () => Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");

async function customer({ withTrial = false } = {}) {
  const email = `cliente-${randomUUID().slice(0, 8)}@pruebas.lotbot.es`;
  const [row] = await sql`
    INSERT INTO lotbot.customers (email, email_normalized, name) VALUES (${email}, ${email}, 'Cliente de pruebas') RETURNING id`;
  let trialKey = null;
  if (withTrial) {
    trialKey = `LOTB-${block()}-${block()}-${block()}`;
    await sql`
      INSERT INTO lotbot.licenses (key, customer_id, kind, max_devices, expires_at)
      VALUES (${trialKey}, ${row.id}, 'prueba', 1, now() + interval '24 hours')`;
  }
  return { id: row.id, email, trialKey };
}

function subscription(customerId, { id = `sub_${randomUUID().replace(/-/g, "")}`, status = "active", periodEnd = now() + 30 * DAY,
  plan = "mensual", interval = "month", cancelAtPeriodEnd = false, cancelAt = null, endedAt = null, amount = 2900 } = {}) {
  return {
    id, object: "subscription", status, customer: `cus_${customerId}_pruebas`,
    cancel_at_period_end: cancelAtPeriodEnd, cancel_at: cancelAt, ended_at: endedAt,
    metadata: { customer_id: String(customerId), plan_slug: plan },
    items: { object: "list", data: [{ id: `si_${id}`, current_period_end: periodEnd,
      price: { unit_amount: amount, currency: "eur", recurring: { interval } } }] },
  };
}

async function send(type, object, { created = now(), id = `evt_${randomUUID().replace(/-/g, "")}`, secret = SECRET } = {}) {
  const payload = JSON.stringify({ id, object: "event", type, created, api_version: "2025-08-27.basil", data: { object } });
  const t = now();
  const signature = createHmac("sha256", secret).update(`${t}.${payload}`).digest("hex");
  const response = await fetch(`${BASE}/api/stripe/webhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Stripe-Signature": `t=${t},v1=${signature}` },
    body: payload,
  });
  return { status: response.status, data: await response.json(), id };
}

async function licenseOf(subId) {
  const [row] = await sql`
    SELECT l.*, p.slug AS plan_slug, s.status AS sub_status FROM lotbot.subscriptions s
    JOIN lotbot.licenses l ON l.id = s.license_id LEFT JOIN lotbot.plans p ON p.id = l.plan_id
    WHERE s.stripe_subscription_id = ${subId}`;
  return row;
}

const secs = (date) => Math.round(new Date(date).getTime() / 1000);

async function refresh(key, fingerprint) {
  const response = await fetch(`${BASE}/api/v1/license/${fingerprint ? "refresh" : "activate"}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Forwarded-For": `10.8.${randomInt(250)}.${randomInt(250)}` },
    body: JSON.stringify({ key, device: { fingerprint: fingerprint ?? `pc-${randomUUID().replace(/-/g, "")}` } }),
  });
  return { status: response.status, data: await response.json() };
}

test("(preparación) base de PRUEBAS sin el freno de pedidos de ejecuciones anteriores", async () => {
  await sql`DELETE FROM lotbot.login_attempts WHERE scope = 'pedido'`;
});

test("la base de datos tiene las suscripciones (esquema 3 o posterior)", async () => {
  const health = await (await fetch(`${BASE}/api/health`)).json();
  assert.ok(health.schema >= 3);
});

test("un aviso sin firma o con otra firma se rechaza", async () => {
  const c = await customer();
  const bad = await send("customer.subscription.created", subscription(c.id), { secret: "whsec_otra" });
  assert.equal(bad.status, 400);
  const none = await fetch(`${BASE}/api/stripe/webhook`, { method: "POST", body: "{}" });
  assert.equal(none.status, 400);
  const [{ count }] = await sql`SELECT count(*)::int AS count FROM lotbot.subscriptions WHERE customer_id = ${c.id}`;
  assert.equal(count, 0);
});

test("suscripción nueva → licencia de pago hasta fin de periodo + 5 días, y funciona en LOT Bot", async () => {
  const c = await customer();
  const end = now() + 30 * DAY;
  const sub = subscription(c.id, { periodEnd: end });
  const r = await send("customer.subscription.created", sub);
  assert.equal(r.status, 200, JSON.stringify(r.data));
  const lic = await licenseOf(sub.id);
  assert.equal(lic.kind, "pago");
  assert.equal(lic.status, "activa");
  assert.equal(lic.plan_slug, "mensual");
  assert.equal(lic.customer_id, c.id);
  assert.equal(secs(lic.expires_at), end + 5 * DAY);
  const [cust] = await sql`SELECT stripe_customer_id FROM lotbot.customers WHERE id = ${c.id}`;
  assert.equal(cust.stripe_customer_id, sub.customer);
  const activation = await refresh(lic.key);
  assert.equal(activation.status, 200, JSON.stringify(activation.data));
});

test("el mismo aviso dos veces no hace nada dos veces", async () => {
  const c = await customer();
  const sub = subscription(c.id);
  const first = await send("customer.subscription.created", sub);
  const again = await send("customer.subscription.created", sub, { id: first.id });
  assert.equal(again.status, 200);
  assert.equal(again.data.duplicate, true);
  const [{ count }] = await sql`SELECT count(*)::int AS count FROM lotbot.licenses WHERE customer_id = ${c.id}`;
  assert.equal(count, 1);
});

test("quien tenía la prueba gratis conserva SU clave al suscribirse", async () => {
  const c = await customer({ withTrial: true });
  const sub = subscription(c.id, { plan: "anual", interval: "year", periodEnd: now() + 365 * DAY, amount: 24900 });
  await send("customer.subscription.created", sub);
  const lic = await licenseOf(sub.id);
  assert.equal(lic.key, c.trialKey);
  assert.equal(lic.kind, "pago");
  assert.equal(lic.plan_slug, "anual");
  assert.equal(lic.max_devices, 2);
});

test("renovación: el nuevo periodo alarga la licencia", async () => {
  const c = await customer();
  const sub = subscription(c.id, { periodEnd: now() + 2 * DAY });
  await send("customer.subscription.created", sub, { created: now() - 10 });
  const renewed = { ...sub, items: { ...sub.items, data: [{ ...sub.items.data[0], current_period_end: now() + 32 * DAY }] } };
  await send("customer.subscription.updated", renewed);
  const lic = await licenseOf(sub.id);
  assert.equal(secs(lic.expires_at), renewed.items.data[0].current_period_end + 5 * DAY);
});

test("pago fallido (past_due): sigue funcionando con el margen de 5 días", async () => {
  const c = await customer();
  const end = now() + 1 * DAY;
  const sub = subscription(c.id, { periodEnd: end });
  await send("customer.subscription.created", sub, { created: now() - 10 });
  await send("customer.subscription.updated", { ...sub, status: "past_due" });
  const lic = await licenseOf(sub.id);
  assert.equal(lic.status, "activa");
  assert.equal(secs(lic.expires_at), end + 5 * DAY);
});

test("impagada (unpaid) → suspendida; al pagar vuelve a estar activa", async () => {
  const c = await customer();
  const sub = subscription(c.id);
  await send("customer.subscription.created", sub, { created: now() - 20 });
  await send("customer.subscription.updated", { ...sub, status: "unpaid" }, { created: now() - 10 });
  let lic = await licenseOf(sub.id);
  assert.equal(lic.status, "suspendida");
  assert.equal(lic.status_reason, "Impago (Stripe)");
  const blocked = await refresh(lic.key);
  assert.equal(blocked.data.code, "LICENSE_SUSPENDED");
  await send("customer.subscription.updated", { ...sub, status: "active" });
  lic = await licenseOf(sub.id);
  assert.equal(lic.status, "activa");
  assert.equal(lic.status_reason, "");
});

test("una suspensión hecha a mano en /admin no la deshace Stripe", async () => {
  const c = await customer();
  const sub = subscription(c.id);
  await send("customer.subscription.created", sub, { created: now() - 10 });
  let lic = await licenseOf(sub.id);
  await sql`UPDATE lotbot.licenses SET status = 'suspendida', status_reason = 'Fraude' WHERE id = ${lic.id}`;
  await send("customer.subscription.updated", sub);
  lic = await licenseOf(sub.id);
  assert.equal(lic.status, "suspendida");
  assert.equal(lic.status_reason, "Fraude");
});

test("cancelada al final del periodo: vale justo hasta el fin del periodo (sin margen)", async () => {
  const c = await customer();
  const end = now() + 10 * DAY;
  const sub = subscription(c.id, { periodEnd: end });
  await send("customer.subscription.created", sub, { created: now() - 10 });
  await send("customer.subscription.updated", { ...sub, cancel_at_period_end: true });
  const lic = await licenseOf(sub.id);
  assert.equal(secs(lic.expires_at), end);
});

test("cancelada del todo → la licencia termina y LOT Bot recibe LICENSE_EXPIRED", async () => {
  const c = await customer();
  const sub = subscription(c.id);
  await send("customer.subscription.created", sub, { created: now() - 10 });
  let lic = await licenseOf(sub.id);
  const device = `pc-${randomUUID().replace(/-/g, "")}`;
  const activated = await fetch(`${BASE}/api/v1/license/activate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key: lic.key, device: { fingerprint: device } }),
  });
  assert.equal(activated.status, 200);
  await send("customer.subscription.deleted", { ...sub, status: "canceled", ended_at: now() - 5 });
  lic = await licenseOf(sub.id);
  assert.ok(new Date(lic.expires_at) <= new Date());
  const after = await refresh(lic.key, device);
  assert.equal(after.data.code, "LICENSE_EXPIRED");
});

test("un aviso viejo que llega tarde no pisa al nuevo", async () => {
  const c = await customer();
  const sub = subscription(c.id);
  await send("customer.subscription.created", sub, { created: now() - 60 });
  await send("customer.subscription.updated", { ...sub, status: "canceled", ended_at: now() }, { created: now() });
  await send("customer.subscription.updated", { ...sub, status: "active" }, { created: now() - 30 });
  const lic = await licenseOf(sub.id);
  assert.equal(lic.sub_status, "canceled");
  assert.ok(new Date(lic.expires_at) <= new Date());
});

test("volver a suscribirse tras cancelar reutiliza la misma clave", async () => {
  const c = await customer();
  const first = subscription(c.id);
  await send("customer.subscription.created", first, { created: now() - 20 });
  const key = (await licenseOf(first.id)).key;
  await send("customer.subscription.deleted", { ...first, status: "canceled", ended_at: now() - 15 }, { created: now() - 15 });
  const second = subscription(c.id);
  await send("customer.subscription.created", second);
  const lic = await licenseOf(second.id);
  assert.equal(lic.key, key);
  assert.equal(lic.status, "activa");
  assert.ok(new Date(lic.expires_at) > new Date());
  // Un aviso tardío de la suscripción vieja no la vuelve a cortar.
  await send("customer.subscription.updated", { ...first, status: "canceled", ended_at: now() - 15 });
  assert.ok(new Date((await licenseOf(second.id)).expires_at) > new Date());
});

test("comprar con tarjeta con el email de un cliente existente obliga a entrar en Mi cuenta", async () => {
  const c = await customer({ withTrial: true });
  const response = await fetch(`${BASE}/api/checkout`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan: "mensual", method: "tarjeta", email: c.email, name: "X", accept: true }),
  });
  const data = await response.json();
  assert.equal(response.status, 409, JSON.stringify(data));
  assert.match(data.error, /Mi cuenta/);
  const [{ count }] = await sql`SELECT count(*)::int AS count FROM lotbot.subscriptions WHERE customer_id = ${c.id}`;
  assert.equal(count, 0);
});

test("si Stripe no responde, el pago con tarjeta da un error claro (no se rompe)", async () => {
  const response = await fetch(`${BASE}/api/checkout`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan: "mensual", method: "tarjeta", email: `nuevo-${randomUUID().slice(0, 8)}@pruebas.lotbot.es`, accept: true }),
  });
  const data = await response.json();
  assert.equal(response.status, 502, JSON.stringify(data));
  assert.match(data.error, /tarjeta/);
});

test("al terminar", async () => {
  await sql.end();
});
