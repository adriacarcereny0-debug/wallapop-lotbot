/**
 * Verificación en dos pasos de /admin (TOTP, RFC 6238): códigos de 6 cifras
 * que cambian cada 30 s en una app (Google Authenticator, Authy, 1Password…).
 *
 * El secreto se guarda CIFRADO (AES-256-GCM con una clave derivada de
 * SESSION_SECRET) en los ajustes. Un código ya usado no vale dos veces.
 */
import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { getSetting, setSetting } from "./db";
import { secret } from "./util";

const KEY = "admin_2fa";
const STEP = 30;
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

type Stored = { enc: string; enabled: boolean; last_step: number };

export function base32Encode(data: Buffer): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of data) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += B32[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) out += B32[(value << (5 - bits)) & 31];
  return out;
}

export function base32Decode(text: string): Buffer {
  const clean = text.replace(/[\s=]/g, "").toUpperCase();
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const char of clean) {
    const index = B32.indexOf(char);
    if (index < 0) throw new Error("Base32 no válido");
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 255);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

export function totp(secretB32: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const hmac = createHmac("sha1", base32Decode(secretB32)).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 15;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

function aesKey(): Buffer {
  return createHash("sha256").update(`2fa|${secret()}`).digest();
}

function encrypt(text: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", aesKey(), iv);
  const body = Buffer.concat([cipher.update(text, "utf8"), cipher.final()]);
  return [iv, cipher.getAuthTag(), body].map((b) => b.toString("base64")).join(".");
}

function decrypt(value: string): string {
  const [iv, tag, body] = value.split(".").map((p) => Buffer.from(p, "base64"));
  const decipher = createDecipheriv("aes-256-gcm", aesKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(body), decipher.final()]).toString("utf8");
}

async function stored(): Promise<Stored | null> {
  const value = await getSetting<Stored | null>(KEY, null);
  return value && value.enc ? value : null;
}

export async function twoFactorEnabled(): Promise<boolean> {
  return Boolean((await stored())?.enabled);
}

/** Paso 1: secreto nuevo (aún sin activar). Devuelve el secreto y el enlace para la app. */
export async function startSetup(): Promise<{ secret: string; uri: string }> {
  const current = await stored();
  if (current?.enabled) throw new Error("Ya está activada.");
  const fresh = base32Encode(randomBytes(20));
  await setSetting(null, KEY, { enc: encrypt(fresh), enabled: false, last_step: 0 });
  return { secret: fresh, uri: `otpauth://totp/LOT%20Bot:admin?secret=${fresh}&issuer=LOT%20Bot&digits=6&period=30` };
}

export async function pendingSecret(): Promise<string | null> {
  const current = await stored();
  return current && !current.enabled ? decrypt(current.enc) : null;
}

/** Comprueba un código (±30 s) y lo «gasta» para que no se pueda repetir. */
export async function verifyCode(code: string, now = Date.now()): Promise<boolean> {
  const current = await stored();
  if (!current || !/^\d{6}$/.test(code.trim())) return false;
  const key = decrypt(current.enc);
  const step = Math.floor(now / 1000 / STEP);
  for (const candidate of [step - 1, step, step + 1]) {
    if (candidate <= current.last_step) continue;
    const expected = Buffer.from(totp(key, candidate));
    const given = Buffer.from(code.trim());
    if (expected.length === given.length && timingSafeEqual(expected, given)) {
      await setSetting(null, KEY, { ...current, last_step: candidate });
      return true;
    }
  }
  return false;
}

/** Paso 2: activar con un código de la app (prueba que está bien configurada). */
export async function confirmSetup(code: string): Promise<boolean> {
  const current = await stored();
  if (!current || current.enabled) return false;
  if (!(await verifyCode(code))) return false;
  const after = await stored();
  await setSetting(null, KEY, { ...(after as Stored), enabled: true });
  return true;
}

export async function disable(code: string): Promise<boolean> {
  if (!(await twoFactorEnabled()) || !(await verifyCode(code))) return false;
  await setSetting(null, KEY, { enc: "", enabled: false, last_step: 0 });
  return true;
}
