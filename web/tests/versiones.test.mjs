/**
 * Versiones y actualizaciones: registrar (GitHub Actions), buscar (LOT Bot),
 * despliegue gradual, obligatorias, retiradas, firma y descarga.
 *
 *   La web de pruebas arranca con RELEASE_API_TOKEN=token-de-pruebas-versiones-123456
 *   BASE_URL=... DATABASE_URL=... RELEASE_API_TOKEN=... npm test
 */
import assert from "node:assert/strict";
import { createHash, createPublicKey, randomInt, randomUUID, verify } from "node:crypto";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const TOKEN = process.env.RELEASE_API_TOKEN ?? "token-de-pruebas-versiones-123456";
const sql = postgres(process.env.DATABASE_URL, { max: 2, onnotice: () => {} });
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const block = () => Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");
// Versiones altas y únicas por ejecución, para no chocar con otras pruebas.
const major = 900 + randomInt(90);
let minor = 0;
const nextVersion = () => `${major}.${++minor}.0`;
const sha = (text) => createHash("sha256").update(text).digest("hex");

async function register(body, token = TOKEN) {
  const response = await fetch(`${BASE}/api/v1/releases`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  return { status: response.status, data: await response.json() };
}

async function activeDevice() {
  const key = `LOTB-${block()}-${block()}-${block()}`;
  await sql`
    INSERT INTO lotbot.licenses (key, kind, plan_id, max_devices, expires_at)
    VALUES (${key}, 'pago', (SELECT id FROM lotbot.plans WHERE slug = 'mensual'), 1, now() + interval '30 days')`;
  const fingerprint = `pc-${randomUUID().replace(/-/g, "")}`;
  const response = await fetch(`${BASE}/api/v1/license/activate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, device: { fingerprint } }),
  });
  assert.equal(response.status, 200);
  return { key, fingerprint };
}

async function check({ key, fingerprint }, current, { platform = "windows-x64", channel = "estable" } = {}) {
  const response = await fetch(`${BASE}/api/v1/updates/check`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, device: { fingerprint, app_version: current }, platform, channel }),
  });
  return { status: response.status, data: await response.json() };
}

function asset(platform, version, extra = {}) {
  const content = `instalador ${platform} ${version}`;
  return { platform, name: `LOT-Bot-${version}-${platform}.bin`, sha256: sha(content), size: content.length, url: `https://descargas.ejemplo.es/${version}/${platform}`, ...extra };
}

let publicKey;
async function verifyToken(token) {
  if (!publicKey) {
    const { public_key } = await (await fetch(`${BASE}/api/v1/public-key`)).json();
    publicKey = createPublicKey({ key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(public_key, "base64")]), format: "der", type: "spki" });
  }
  const [prefix, body, signature] = token.split(".");
  return {
    ok: verify(null, Buffer.from(`${prefix}.${body}`), publicKey, Buffer.from(signature, "base64url")),
    payload: JSON.parse(Buffer.from(body, "base64url").toString("utf8")),
  };
}

test("(preparación) base de PRUEBAS sin versiones anteriores en oferta", async () => {
  await sql`UPDATE lotbot.releases SET status = 'retirada' WHERE status = 'activa'`;
});

test("sin token (o con uno malo) no se puede registrar una versión", async () => {
  const body = { version: nextVersion(), assets: [asset("windows-x64", "9.9.9")] };
  assert.equal((await register(body, "")).status, 401);
  assert.equal((await register(body, "otro-token-que-no-es-el-bueno-000")).status, 401);
});

test("datos malos al registrar se rechazan", async () => {
  assert.equal((await register({ version: "1.2", assets: [asset("windows-x64", "1.2")] })).status, 400);
  assert.equal((await register({ version: nextVersion(), assets: [asset("linux", "x")] })).status, 400);
  assert.equal((await register({ version: nextVersion(), assets: [{ ...asset("windows-x64", "x"), sha256: "abc" }] })).status, 400);
  assert.equal((await register({ version: nextVersion(), assets: [{ ...asset("windows-x64", "x"), url: "http://inseguro" }] })).status, 400);
});

test("hay versión nueva: pase firmado con versión, plataforma, huella y ordenador", async () => {
  const device = await activeDevice();
  const version = nextVersion();
  const win = asset("windows-x64", version);
  const r = await register({ version, notes: "Mejoras", assets: [win, asset("mac-arm64", version)] });
  assert.equal(r.status, 200, JSON.stringify(r.data));
  const { status, data } = await check(device, `${major}.0.0`);
  assert.equal(status, 200, JSON.stringify(data));
  assert.equal(data.update.version, version);
  assert.equal(data.update.sha256, win.sha256);
  const { ok, payload } = await verifyToken(data.update.token);
  assert.ok(ok, "firma válida");
  assert.equal(payload.typ, "lotbot-update");
  assert.equal(payload.ver, version);
  assert.equal(payload.plat, "windows-x64");
  assert.equal(payload.sha256, win.sha256);
  assert.equal(payload.size, win.size);
  assert.equal(payload.dev, device.fingerprint);
  // Descarga: redirige al instalador (url guardada, sin GitHub configurado).
  const download = await fetch(data.update.download, { redirect: "manual" });
  assert.equal(download.status, 302);
  assert.equal(download.headers.get("location"), win.url);
  // Con la misma versión ya instalada, no hay nada nuevo.
  const same = await check(device, version);
  assert.equal(same.data.update?.version === version, false);
});

test("sin licencia válida no se ofrecen actualizaciones", async () => {
  const device = await activeDevice();
  await sql`UPDATE lotbot.licenses SET status = 'revocada' WHERE key = ${device.key}`;
  const { status, data } = await check(device, "1.0.0");
  assert.equal(status, 403);
  assert.equal(data.code, "LICENSE_REVOKED");
  const stranger = await check({ key: device.key, fingerprint: `pc-${randomUUID().replace(/-/g, "")}` }, "1.0.0");
  assert.notEqual(stranger.status, 200);
});

test("un enlace de descarga manipulado o de una licencia caducada no sirve", async () => {
  const device = await activeDevice();
  const version = nextVersion();
  await register({ version, assets: [asset("windows-x64", version)] });
  const { data } = await check(device, `${major}.0.0`);
  const url = new URL(data.update.download);
  const ticket = url.searchParams.get("t");
  const [rel, lic, exp, sig] = ticket.split(".");
  const forged = `${BASE}/api/v1/updates/download?t=${rel}.${lic}.${Number(exp) + 99999}.${sig}`;
  assert.equal((await fetch(forged, { redirect: "manual" })).status, 403);
  await sql`UPDATE lotbot.licenses SET expires_at = now() - interval '1 minute' WHERE key = ${device.key}`;
  assert.equal((await fetch(data.update.download, { redirect: "manual" })).status, 403);
});

test("despliegue gradual: con 0 % no llega; con 100 % llega a todos", async () => {
  const devices = await Promise.all([1, 2, 3, 4, 5].map(() => activeDevice()));
  const version = nextVersion();
  const base = `${major}.${minor}.0`.replace(/\.\d+\.0$/, `.${minor - 1}.9`);
  await register({ version, rollout_percent: 0, assets: [asset("windows-x64", version)] });
  for (const device of devices) {
    const { data } = await check(device, base);
    assert.notEqual(data.update?.version, version);
  }
  await sql`UPDATE lotbot.releases SET rollout_percent = 100 WHERE version = ${version}`;
  for (const device of devices) {
    const { data } = await check(device, base);
    assert.equal(data.update?.version, version);
  }
});

test("una versión obligatoria no espera turno y una retirada no se ofrece", async () => {
  const device = await activeDevice();
  const version = nextVersion();
  const base = `${major}.${minor - 1}.9`;
  await register({ version, rollout_percent: 0, mandatory: true, assets: [asset("windows-x64", version)] });
  let { data } = await check(device, base);
  assert.equal(data.update?.version, version);
  assert.equal(data.update.mandatory, true);
  await sql`UPDATE lotbot.releases SET status = 'retirada' WHERE version = ${version}`;
  ({ data } = await check(device, base));
  assert.notEqual(data.update?.version, version);
});

test("el canal beta solo lo recibe quien lo pide; cada plataforma recibe la suya", async () => {
  const device = await activeDevice();
  const version = nextVersion();
  const base = `${major}.${minor - 1}.9`;
  await register({ version, channel: "beta", assets: [asset("mac-intel", version)] });
  assert.notEqual((await check(device, base, { platform: "mac-intel" })).data.update?.version, version);
  assert.equal((await check(device, base, { platform: "mac-intel", channel: "beta" })).data.update?.version, version);
  assert.notEqual((await check(device, base, { platform: "windows-x64", channel: "beta" })).data.update?.version, version);
});

test("un cliente marcado como beta recibe las versiones beta sin pedirlas", async () => {
  const device = await activeDevice();
  const version = nextVersion();
  const base = `${major}.${minor - 1}.9`;
  await register({ version, channel: "beta", assets: [asset("windows-x64", version)] });
  assert.notEqual((await check(device, base)).data.update?.version, version);
  const [{ id }] = await sql`
    INSERT INTO lotbot.customers (email, email_normalized) VALUES (${`beta-${randomUUID().slice(0, 8)}@pruebas.es`}, 'x') RETURNING id`;
  await sql`UPDATE lotbot.customers SET beta = true WHERE id = ${id}`;
  await sql`UPDATE lotbot.licenses SET customer_id = ${id} WHERE key = ${device.key}`;
  assert.equal((await check(device, base)).data.update?.version, version);
});

test("/admin/versiones pide contraseña", async () => {
  const response = await fetch(`${BASE}/admin/versiones`, { redirect: "manual" });
  assert.ok([302, 303, 307].includes(response.status));
});

test("al terminar", async () => {
  await sql.end();
});
