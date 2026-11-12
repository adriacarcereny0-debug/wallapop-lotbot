/**
 * API de licencias v1 (la que usará LOT Bot): activar, renovar, desvincular,
 * límites de ordenadores, suspender/revocar y firma de los pases.
 *
 *   BASE_URL=http://localhost:3100 DATABASE_URL=postgres://... npm test
 */
import assert from "node:assert/strict";
import { createPublicKey, randomInt, randomUUID, verify } from "node:crypto";
import { writeFileSync } from "node:fs";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const sql = postgres(process.env.DATABASE_URL, { max: 2, onnotice: () => {} });
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const block = () => Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");
const ip = () => `10.9.${randomInt(250)}.${randomInt(250)}`;
const fp = (name = "") => `pc-${name}-${randomUUID().replace(/-/g, "")}`.slice(0, 60);

async function newLicense({ kind = "pago", devices = 1, days = 30, plan = "mensual" } = {}) {
  const key = `LOTB-${block()}-${block()}-${block()}`;
  const [row] = await sql`
    INSERT INTO lotbot.licenses (key, kind, plan_id, max_devices, expires_at)
    VALUES (${key}, ${kind}, (SELECT id FROM lotbot.plans WHERE slug = ${plan}), ${devices},
            ${days == null ? null : sql`now() + make_interval(days => ${days})`})
    RETURNING id`;
  return { key, id: row.id };
}

async function call(path, key, fingerprint, extra = {}, from = ip()) {
  const response = await fetch(`${BASE}/api/v1/license/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Forwarded-For": from },
    body: JSON.stringify({ key, device: { fingerprint, name: "Portátil de pruebas", os: "Windows 11", app_version: "1.0.0" }, ...extra }),
  });
  return { status: response.status, data: await response.json() };
}

let publicKey;
async function checkToken(token) {
  if (!publicKey) {
    const { public_key } = await (await fetch(`${BASE}/api/v1/public-key`)).json();
    const spki = Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(public_key, "base64")]);
    publicKey = createPublicKey({ key: spki, format: "der", type: "spki" });
  }
  const [prefix, body, signature] = token.split(".");
  assert.equal(prefix, "LBT1");
  const ok = verify(null, Buffer.from(`${prefix}.${body}`), publicKey, Buffer.from(signature, "base64url"));
  return { ok, payload: JSON.parse(Buffer.from(body, "base64url").toString("utf8")) };
}

test("activar devuelve un pase firmado de 72 h para ESTE ordenador", async () => {
  const { key } = await newLicense();
  const device = fp("a");
  const { status, data } = await call("activate", key, device);
  assert.equal(status, 200, JSON.stringify(data));
  const { ok, payload } = await checkToken(data.token);
  assert.ok(ok, "la firma del pase es válida");
  assert.equal(payload.dev, device);
  assert.equal(payload.plan, "mensual");
  assert.equal(payload.seats, 1);
  const hours = (payload.exp - payload.iat) / 3600;
  assert.ok(hours > 71.9 && hours <= 72, `el pase dura ${hours} h`);
  assert.equal(data.license.devices_in_use, 1);
  writeFileSync(process.env.TOKEN_OUT ?? "/dev/null", JSON.stringify({ token: data.token, device, key }));
});

test("un pase cambiado ya no pasa la comprobación de firma", async () => {
  const { key } = await newLicense();
  const { data } = await call("activate", key, fp("t"));
  const [prefix, body, signature] = data.token.split(".");
  const payload = JSON.parse(Buffer.from(body, "base64url").toString());
  payload.exp += 365 * 24 * 3600; // intentar alargarlo un año
  const forged = `${prefix}.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.${signature}`;
  assert.equal((await checkToken(forged)).ok, false);
});

test("el pase nunca dura más que la licencia (prueba de 24 h)", async () => {
  const { key } = await newLicense({ kind: "prueba", days: 1 });
  const { data } = await call("activate", key, fp("p"));
  const { payload } = await checkToken(data.token);
  assert.equal(payload.exp, payload.lic_exp);
  assert.ok((payload.exp - payload.iat) / 3600 <= 24.01);
});

test("mensual: 1 ordenador; anual: 2", async () => {
  const monthly = await newLicense({ devices: 1 });
  assert.equal((await call("activate", monthly.key, fp("m1"))).status, 200);
  const second = await call("activate", monthly.key, fp("m2"));
  assert.equal(second.status, 409);
  assert.equal(second.data.code, "DEVICE_LIMIT");

  const yearly = await newLicense({ devices: 2, days: 365, plan: "anual" });
  assert.equal((await call("activate", yearly.key, fp("y1"))).status, 200);
  assert.equal((await call("activate", yearly.key, fp("y2"))).status, 200);
  assert.equal((await call("activate", yearly.key, fp("y3"))).data.code, "DEVICE_LIMIT");
});

test("volver a activar el mismo ordenador no gasta otra plaza", async () => {
  const { key } = await newLicense({ devices: 1 });
  const device = fp("r");
  assert.equal((await call("activate", key, device)).status, 200);
  const again = await call("activate", key, device);
  assert.equal(again.status, 200);
  assert.equal(again.data.license.devices_in_use, 1);
});

test("dos activaciones a la vez no se saltan el límite", async () => {
  const { key } = await newLicense({ devices: 1 });
  const results = await Promise.all([call("activate", key, fp("c1")), call("activate", key, fp("c2"))]);
  assert.deepEqual(results.map((r) => r.status).sort(), [200, 409]);
});

test("renovar: solo un ordenador activado", async () => {
  const { key } = await newLicense();
  const device = fp("rf");
  await call("activate", key, device);
  const renewed = await call("refresh", key, device);
  assert.equal(renewed.status, 200);
  assert.ok((await checkToken(renewed.data.token)).ok);
  const stranger = await call("refresh", key, fp("x"));
  assert.equal(stranger.data.code, "DEVICE_NOT_ACTIVATED");
});

test("suspender, revocar y reactivar se notan al renovar", async () => {
  const { key, id } = await newLicense();
  const device = fp("s");
  await call("activate", key, device);
  await sql`UPDATE lotbot.licenses SET status = 'suspendida', status_reason = 'impago' WHERE id = ${id}`;
  const suspended = await call("refresh", key, device);
  assert.equal(suspended.status, 403);
  assert.equal(suspended.data.code, "LICENSE_SUSPENDED");
  assert.match(suspended.data.message, /impago/);
  await sql`UPDATE lotbot.licenses SET status = 'revocada' WHERE id = ${id}`;
  assert.equal((await call("refresh", key, device)).data.code, "LICENSE_REVOKED");
  assert.equal((await call("activate", key, fp("s2"))).data.code, "LICENSE_REVOKED");
  await sql`UPDATE lotbot.licenses SET status = 'activa', status_reason = '' WHERE id = ${id}`;
  assert.equal((await call("refresh", key, device)).status, 200);
});

test("una licencia caducada no renueva", async () => {
  const { key, id } = await newLicense();
  const device = fp("e");
  await call("activate", key, device);
  await sql`UPDATE lotbot.licenses SET expires_at = now() - interval '1 minute' WHERE id = ${id}`;
  const result = await call("refresh", key, device);
  assert.equal(result.data.code, "LICENSE_EXPIRED");
});

test("desvincular libera la plaza (máximo 3 cambios al mes)", async () => {
  const { key } = await newLicense({ devices: 1 });
  let current = fp("d0");
  await call("activate", key, current);
  for (let n = 1; n <= 3; n++) {
    assert.equal((await call("deactivate", key, current)).status, 200);
    current = fp(`d${n}`);
    assert.equal((await call("activate", key, current)).status, 200, `cambio ${n}`);
  }
  const fourth = await call("deactivate", key, current);
  assert.equal(fourth.status, 429);
  assert.equal(fourth.data.code, "TOO_MANY_CHANGES");
});

test("un ordenador bloqueado no puede activar esa licencia", async () => {
  const { key, id } = await newLicense({ devices: 2 });
  const device = fp("b");
  await call("activate", key, device);
  await sql`UPDATE lotbot.devices SET status = 'bloqueado' WHERE license_id = ${id} AND fingerprint = ${device}`;
  assert.equal((await call("activate", key, device)).data.code, "DEVICE_BLOCKED");
  assert.equal((await call("refresh", key, device)).data.code, "DEVICE_BLOCKED");
});

test("la prueba gratis es de un solo uso por ordenador", async () => {
  const device = fp("trial");
  const first = await newLicense({ kind: "prueba", days: 1 });
  assert.equal((await call("activate", first.key, device)).status, 200);
  const second = await newLicense({ kind: "prueba", days: 1 });
  const result = await call("activate", second.key, device);
  assert.equal(result.status, 409);
  assert.equal(result.data.code, "TRIAL_ALREADY_USED");
  // Con una licencia de pago, ese ordenador sí puede.
  const paid = await newLicense();
  assert.equal((await call("activate", paid.key, device)).status, 200);
});

test("datos no válidos y claves inexistentes", async () => {
  assert.equal((await call("activate", "no-es-una-clave", fp())).status, 400);
  const { key } = await newLicense();
  assert.equal((await call("activate", key, "corto")).status, 400);
  assert.equal((await call("activate", "LOTB-AAAA-BBBB-CCCC", fp())).data.code, "LICENSE_NOT_FOUND");
});

test("muchos intentos con claves inventadas desde la misma conexión se frenan", async () => {
  const from = ip();
  let last;
  for (let n = 0; n < 21; n++) {
    last = await call("activate", `LOTB-${block()}-${block()}-${block()}`, fp(), {}, from);
  }
  assert.equal(last.status, 429);
  assert.equal(last.data.code, "RATE_LIMITED");
  const { key } = await newLicense();
  assert.equal((await call("activate", key, fp(), {}, from)).status, 429, "también con una clave buena, durante una hora");
});

test("la comprobación antigua (/api/license/verify) sigue funcionando", async () => {
  const { key } = await newLicense({ devices: 1 });
  const response = await fetch(`${BASE}/api/license/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, deviceId: fp("old") }),
  });
  assert.equal((await response.json()).valid, true);
});

test.after(async () => {
  await sql.end();
});
