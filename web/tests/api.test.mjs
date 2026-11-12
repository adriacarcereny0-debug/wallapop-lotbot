/**
 * Pruebas de la API contra la web en marcha y su base de datos.
 *
 *   BASE_URL=http://localhost:3100 DATABASE_URL=postgres://... npm test
 *
 * ¡Usa SIEMPRE una base de datos de pruebas! Estas pruebas la modifican.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const sql = postgres(process.env.DATABASE_URL, { max: 1, onnotice: () => {} });
const run = randomUUID().slice(0, 8);

async function post(path, body, ip = `10.0.${Math.floor(Math.random() * 250)}.${Math.floor(Math.random() * 250)}`) {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Forwarded-For": ip },
    body: JSON.stringify(body),
  });
  return { status: response.status, data: await response.json() };
}

test("la prueba gratis da una clave de 24 h", async () => {
  const { status, data } = await post("/api/trial", { email: `ana.${run}@gmail.com`, name: "Ana", accept: true });
  assert.equal(status, 200, JSON.stringify(data));
  assert.match(data.key, /^LOTB-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  const hours = (new Date(data.expiresAt) - Date.now()) / 3600e3;
  assert.ok(hours > 23.9 && hours <= 24.01, `caduca en ${hours} h`);
});

test("la prueba gratis es de un solo uso (también con alias de Gmail)", async () => {
  const again = await post("/api/trial", { email: `ana.${run}@gmail.com`, accept: true });
  assert.equal(again.status, 409);
  assert.match(again.data.error, /solo uso/);
  const alias = await post("/api/trial", { email: `ANA${run}+otra@googlemail.com`, accept: true });
  assert.equal(alias.status, 409, "un alias de la misma bandeja no da otra prueba");
});

test("un ordenador solo puede pedir una prueba", async () => {
  const device = `pc-${run}`;
  assert.equal((await post("/api/trial", { email: `pc1.${run}@ejemplo.com`, deviceId: device, accept: true })).status, 200);
  const second = await post("/api/trial", { email: `pc2.${run}@ejemplo.com`, deviceId: device, accept: true });
  assert.equal(second.status, 409);
  assert.match(second.data.error, /ordenador/);
});

test("desde la misma conexión, como mucho 2 pruebas", async () => {
  const ip = `192.168.77.${Math.floor(Math.random() * 250)}`;
  for (const n of [1, 2]) {
    assert.equal((await post("/api/trial", { email: `ip${n}.${run}@ejemplo.com`, accept: true }, ip)).status, 200);
  }
  const third = await post("/api/trial", { email: `ip3.${run}@ejemplo.com`, accept: true }, ip);
  assert.equal(third.status, 409);
  assert.match(third.data.error, /conexión/);
});

test("la prueba exige email válido, aceptar la privacidad y no ser un robot", async () => {
  assert.equal((await post("/api/trial", { email: "no-es-un-email", accept: true })).status, 400);
  assert.equal((await post("/api/trial", { email: `x.${run}@ejemplo.com` })).status, 400);
  assert.equal((await post("/api/trial", { email: `y.${run}@ejemplo.com`, accept: true, website: "spam" })).status, 400);
});

test("la licencia se comprueba y se limita a sus ordenadores", async () => {
  const { data } = await post("/api/trial", { email: `lic.${run}@ejemplo.com`, accept: true });
  const first = await post("/api/license/verify", { key: data.key, deviceId: "ordenador-A" });
  assert.equal(first.data.valid, true);
  assert.equal(first.data.kind, "prueba");
  assert.equal((await post("/api/license/verify", { key: data.key, deviceId: "ordenador-A" })).data.valid, true);
  const other = await post("/api/license/verify", { key: data.key, deviceId: "ordenador-B" });
  assert.equal(other.data.valid, false);
  assert.match(other.data.reason, /máximo 1/);
  assert.equal((await post("/api/license/verify", { key: "LOTB-AAAA-BBBB-CCCC" })).data.valid, false);
});

test("una prueba caducada ya no vale", async () => {
  const { data } = await post("/api/trial", { email: `caduca.${run}@ejemplo.com`, accept: true });
  await sql`UPDATE lotbot.licenses SET expires_at = now() - interval '1 minute' WHERE key = ${data.key}`;
  const result = await post("/api/license/verify", { key: data.key, deviceId: "x" });
  assert.equal(result.data.valid, false);
  assert.match(result.data.reason, /terminado/);
});

test("sin formas de pago listas no se puede comprar; con Bizum, sí", async () => {
  await sql`UPDATE lotbot.payment_methods SET enabled = false, instructions = '' WHERE id <> 'tarjeta'`;
  const none = await post("/api/checkout", { plan: "mensual", method: "bizum", email: `c.${run}@ejemplo.com`, accept: true });
  assert.equal(none.status, 400);
  await sql`UPDATE lotbot.payment_methods SET enabled = true,
    instructions = 'Bizum de {importe} al 600000000 con el concepto {referencia}' WHERE id = 'bizum'`;
  const order = await post("/api/checkout", {
    plan: "mensual", method: "bizum", email: `c.${run}@ejemplo.com`, name: "Carla", accept: true,
  });
  assert.equal(order.status, 200, JSON.stringify(order.data));
  assert.match(order.data.reference, /^LOT-[A-Z2-9]{8}$/);
  const page = await (await fetch(`${BASE}${order.data.redirect}`)).text();
  assert.match(page, new RegExp(`concepto ${order.data.reference}`));
  assert.match(page, /Pedido pendiente de pago/);
  // Sin claves de Stripe, la tarjeta no se ofrece.
  const card = await post("/api/checkout", { plan: "mensual", method: "tarjeta", email: `c.${run}@ejemplo.com`, accept: true });
  assert.equal(card.status, 400);
});

test("un plan que no existe no se puede comprar", async () => {
  const result = await post("/api/checkout", { plan: "gratis-para-siempre", method: "bizum", email: `d.${run}@ejemplo.com`, accept: true });
  assert.equal(result.status, 400);
});

test("el aviso de Stripe sin firma se rechaza", async () => {
  const response = await fetch(`${BASE}/api/stripe/webhook`, { method: "POST", body: "{}" });
  assert.equal(response.status, 400);
});

test("/admin pide contraseña", async () => {
  for (const path of ["/admin", "/admin/pedidos", "/admin/licencias", "/admin/planes"]) {
    const response = await fetch(`${BASE}${path}`, { redirect: "manual" });
    assert.equal(response.status, 307, path);
    assert.match(response.headers.get("location") ?? "", /\/admin\/login/);
  }
});

test.after(async () => {
  await sql.end();
});
