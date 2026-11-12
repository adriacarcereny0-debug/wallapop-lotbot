/**
 * Integridad: lista firmada de huellas por versión y plataforma, y aviso en
 * /admin/alertas cuando un ordenador cuenta que su instalación no coincide.
 */
import assert from "node:assert/strict";
import { createHash, createHmac, randomInt, randomUUID } from "node:crypto";
import { test } from "node:test";

import postgres from "postgres";

const BASE = process.env.BASE_URL ?? "http://localhost:3100";
const TOKEN = process.env.RELEASE_API_TOKEN ?? "token-de-pruebas-versiones-123456";
const sql = postgres(process.env.DATABASE_URL, { max: 2, onnotice: () => {} });
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const block = () => Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");
const sha = (t) => createHash("sha256").update(t).digest("hex");
const post = async (path, body, headers = {}) => {
  const r = await fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  return { status: r.status, data: await r.json() };
};

async function device() {
  const key = `LOTB-${block()}-${block()}-${block()}`;
  await sql`INSERT INTO lotbot.licenses (key, kind, max_devices, expires_at) VALUES (${key}, 'pago', 1, now() + interval '30 days')`;
  const fingerprint = `pc-${randomUUID().replace(/-/g, "")}`;
  assert.equal((await post("/api/v1/license/activate", { key, device: { fingerprint } })).status, 200);
  return { key, fingerprint };
}

test("la lista de huellas va firmada, para esa versión, plataforma y ordenador", async () => {
  const version = `${700 + randomInt(90)}.${randomInt(900)}.${randomInt(900)}`;
  const files = { "LOT-Bot.exe": sha("exe oficial") };
  const reg = await post("/api/v1/releases", {
    version, assets: [{ platform: "windows-x64", name: "s.exe", sha256: sha("s"), size: 1, url: "https://x.es/s", manifest: files }],
  }, { Authorization: `Bearer ${TOKEN}` });
  assert.equal(reg.status, 200, JSON.stringify(reg.data));
  const d = await device();
  const { status, data } = await post("/api/v1/integrity", { key: d.key, device: { fingerprint: d.fingerprint, app_version: version }, platform: "windows-x64" });
  assert.equal(status, 200);
  const payload = JSON.parse(Buffer.from(data.token.split(".")[1], "base64url").toString());
  assert.equal(payload.typ, "lotbot-integrity");
  assert.deepEqual(payload.files, files);
  assert.equal(payload.dev, d.fingerprint);
  // Versión sin lista: no hay nada que comprobar.
  const none = await post("/api/v1/integrity", { key: d.key, device: { fingerprint: d.fingerprint, app_version: "1.0.0" }, platform: "windows-x64" });
  assert.equal(none.data.token, null);
});

test("listas con rutas peligrosas no se aceptan al registrar", async () => {
  const bad = await post("/api/v1/releases", {
    version: `${700 + randomInt(90)}.1.1`, assets: [{ platform: "windows-x64", name: "s", sha256: sha("s"), size: 1, url: "https://x.es/s", manifest: { "../fuera": sha("x") } }],
  }, { Authorization: `Bearer ${TOKEN}` });
  assert.equal(bad.status, 400);
});

test("sin licencia no hay lista; el resultado «modificada» sale en Alertas", async () => {
  const stranger = await post("/api/v1/integrity", { key: `LOTB-${block()}-${block()}-${block()}`, device: { fingerprint: `pc-${randomUUID().replace(/-/g, "")}`, app_version: "1.0.0" }, platform: "windows-x64" });
  assert.equal(stranger.status, 404);
  const d = await device();
  const bad = await post("/api/v1/integrity/report", { key: d.key, device: { fingerprint: d.fingerprint }, result: "inventado" });
  assert.equal(bad.status, 400);
  const ok = await post("/api/v1/integrity/report", { key: d.key, device: { fingerprint: d.fingerprint, app_version: "1.0.0" }, result: "modificada", detail: "LOT-Bot.exe" });
  assert.equal(ok.status, 200);
  const secret = process.env.SESSION_SECRET ?? "secreto-de-pruebas";
  const expires = String(Date.now() + 3600 * 1000);
  const cookie = `lotbot_admin=${expires}.${createHmac("sha256", `admin|${secret}`).update(expires).digest("hex")}`;
  const page = await (await fetch(`${BASE}/admin/alertas`, { headers: { Cookie: cookie } })).text();
  assert.match(page, /Instalación modificada/);
  assert.match(page, new RegExp(d.key));
});

test("al terminar", async () => {
  await sql.end();
});
