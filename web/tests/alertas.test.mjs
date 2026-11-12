/**
 * Alertas de posible abuso: conexiones distintas por licencia, cambios de
 * ordenador y claves inventadas. Se comprueba lo que registra la API y lo que
 * enseña /admin/alertas (con sesión de admin).
 *
 *   BASE_URL=... DATABASE_URL=... SESSION_SECRET=(el de la web de pruebas) npm test
 */
import assert from "node:assert/strict";
import { createHmac, randomInt, randomUUID } from "node:crypto";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const sql = postgres(process.env.DATABASE_URL, { max: 2, onnotice: () => {} });
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const block = () => Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");

async function license() {
  const key = `LOTB-${block()}-${block()}-${block()}`;
  const [row] = await sql`
    INSERT INTO lotbot.licenses (key, kind, plan_id, max_devices, expires_at)
    VALUES (${key}, 'pago', (SELECT id FROM lotbot.plans WHERE slug = 'mensual'), 1, now() + interval '30 days')
    RETURNING id`;
  return { key, id: row.id };
}

function call(path, key, fingerprint, ip) {
  return fetch(`${BASE}/api/v1/license/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Forwarded-For": ip },
    body: JSON.stringify({ key, device: { fingerprint } }),
  });
}

async function adminAlertsPage() {
  // Cookie de /admin firmada igual que la web (SESSION_SECRET de la web de pruebas).
  const secret = process.env.SESSION_SECRET ?? "secreto-de-pruebas";
  const expires = String(Date.now() + 3600 * 1000);
  const signature = createHmac("sha256", `admin|${secret}`).update(expires).digest("hex");
  const response = await fetch(`${BASE}/admin/alertas`, { headers: { Cookie: `lotbot_admin=${expires}.${signature}` }, redirect: "manual" });
  assert.equal(response.status, 200, "sesión de admin");
  return response.text();
}

test("cada comprobación apunta la conexión (huella de la IP, nunca la IP)", async () => {
  const { key, id } = await license();
  const fp = `pc-${randomUUID().replace(/-/g, "")}`;
  assert.equal((await call("activate", key, fp, "10.77.0.1")).status, 200);
  assert.equal((await call("refresh", key, fp, "10.77.0.2")).status, 200);
  assert.equal((await call("refresh", key, fp, "10.77.0.2")).status, 200);
  const rows = await sql`SELECT ip_hash, checks FROM lotbot.license_connections WHERE license_id = ${id} ORDER BY checks`;
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.checks), [1, 2]);
  for (const r of rows) assert.doesNotMatch(r.ip_hash, /10\.77/);
});

test("una licencia usada desde muchas conexiones sale en Alertas; una normal, no", async () => {
  const shared = await license();
  const normal = await license();
  const fp = `pc-${randomUUID().replace(/-/g, "")}`;
  const fp2 = `pc-${randomUUID().replace(/-/g, "")}`;
  assert.equal((await call("activate", shared.key, fp, "10.78.0.1")).status, 200);
  for (let i = 2; i <= 6; i++) assert.equal((await call("refresh", shared.key, fp, `10.78.0.${i}`)).status, 200);
  assert.equal((await call("activate", normal.key, fp2, "10.79.0.1")).status, 200);
  const page = await adminAlertsPage();
  assert.match(page, new RegExp(shared.key));
  assert.match(page, /Muchas conexiones distintas/);
  assert.doesNotMatch(page, new RegExp(normal.key));
});

test("cambiar mucho de ordenador sale en Alertas", async () => {
  const { key, id } = await license();
  for (let i = 0; i < 7; i++) {
    await sql`INSERT INTO lotbot.license_events (license_id, kind, fingerprint) VALUES (${id}, 'activacion', ${`pc-${i}`})`;
  }
  const page = await adminAlertsPage();
  assert.match(page, new RegExp(key));
  assert.match(page, /Cambia mucho de ordenador/);
});

test("probar claves inventadas sale en Alertas", async () => {
  const ip = `10.80.${randomInt(250)}.${randomInt(250)}`;
  for (let i = 0; i < 10; i++) await call("refresh", `LOTB-${block()}-${block()}-${block()}`, `pc-${randomUUID().replace(/-/g, "")}`, ip);
  const page = await adminAlertsPage();
  assert.match(page, /Prueban claves inventadas/);
});

test("al terminar", async () => {
  await sql.end();
});
