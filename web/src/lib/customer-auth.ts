/**
 * Cuentas de cliente (/cuenta): email + contraseña.
 *
 * - La contraseña se guarda con scrypt (sal propia por cliente), nunca en claro.
 * - La sesión es una cookie firmada (HMAC con SESSION_SECRET) que lleva el
 *   cliente, la caducidad y una «versión»: al cambiar la contraseña sube la
 *   versión y se cierran todas las sesiones abiertas.
 * - Tras varios intentos fallidos desde la misma conexión se bloquea un rato.
 * - Sin servicio de email: para poner o recuperar la contraseña se usa un
 *   enlace de un solo uso (lo genera el pago con Stripe o el admin).
 */
import { createHash, createHmac, randomBytes, scrypt as scryptCb, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { db, logEvent } from "./db";
import { clientIp, hashIp, normalizeEmail } from "./util";

const scrypt = promisify(scryptCb) as (password: string, salt: Buffer, keylen: number, options: object) => Promise<Buffer>;

const COOKIE = "lotbot_cliente";
const SESSION_DAYS = 30;
export const MIN_PASSWORD = 10;
export const MAX_FAILED_LOGINS = 8;
const LOCK_MINUTES = 15;
const TOKEN_HOURS = 48;
const SCRYPT = { N: 16384, r: 8, p: 1, keylen: 64 };

export type Customer = {
  id: number;
  email: string;
  name: string;
  phone: string;
  founder: boolean;
  stripe_customer_id: string | null;
  has_password: boolean;
};

/** Clave para firmar sesiones: sin SESSION_SECRET (o ADMIN_PASSWORD) no hay cuentas. */
function sessionKey(): string | null {
  const value = process.env.SESSION_SECRET || process.env.ADMIN_PASSWORD || "";
  return value.length >= 8 ? `cliente|${value}` : null;
}

export function accountsConfigured(): boolean {
  return sessionKey() !== null;
}

// ---------------------------------------------------------------------------
// Contraseñas
// ---------------------------------------------------------------------------
export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16);
  const hash = await scrypt(password, salt, SCRYPT.keylen, { N: SCRYPT.N, r: SCRYPT.r, p: SCRYPT.p });
  return `scrypt$${SCRYPT.N}$${SCRYPT.r}$${SCRYPT.p}$${salt.toString("base64")}$${hash.toString("base64")}`;
}

export async function verifyPassword(password: string, stored: string | null): Promise<boolean> {
  if (!stored) return false;
  const [kind, n, r, p, saltB64, hashB64] = stored.split("$");
  if (kind !== "scrypt" || !saltB64 || !hashB64) return false;
  const expected = Buffer.from(hashB64, "base64");
  const actual = await scrypt(password, Buffer.from(saltB64, "base64"), expected.length, {
    N: Number(n), r: Number(r), p: Number(p),
  });
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD) return `La contraseña necesita al menos ${MIN_PASSWORD} caracteres.`;
  if (password.length > 200) return "La contraseña es demasiado larga.";
  return null;
}

// ---------------------------------------------------------------------------
// Sesión
// ---------------------------------------------------------------------------
function sign(payload: string): string {
  return createHmac("sha256", sessionKey() as string).update(payload).digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

async function startSession(customerId: number, version: number): Promise<void> {
  const expires = Date.now() + SESSION_DAYS * 86400 * 1000;
  const payload = `${customerId}.${expires}.${version}`;
  (await cookies()).set(COOKIE, `${payload}.${sign(payload)}`, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_DAYS * 86400,
  });
}

export async function currentCustomer(): Promise<Customer | null> {
  if (!accountsConfigured()) return null;
  const value = (await cookies()).get(COOKIE)?.value;
  if (!value) return null;
  const parts = value.split(".");
  if (parts.length !== 4) return null;
  const [id, expires, version, signature] = parts;
  if (!safeEqual(sign(`${id}.${expires}.${version}`), signature)) return null;
  if (Number(expires) < Date.now()) return null;
  const sql = await db();
  const rows = await sql<(Customer & { session_version: number })[]>`
    SELECT id, email, name, phone, founder, stripe_customer_id, session_version,
           password_hash IS NOT NULL AS has_password
    FROM lotbot.customers WHERE id = ${Number(id)}
  `;
  const customer = rows[0];
  if (!customer || customer.session_version !== Number(version)) return null;
  const { session_version: _ignored, ...rest } = customer;
  return rest;
}

export async function requireCustomer(): Promise<Customer> {
  const customer = await currentCustomer();
  if (!customer) redirect("/cuenta/entrar");
  return customer;
}

export async function logoutCustomer(): Promise<void> {
  (await cookies()).delete({ name: COOKIE, path: "/" });
}

// ---------------------------------------------------------------------------
// Entrar y registrarse
// ---------------------------------------------------------------------------
export type AuthResult = { ok: true } | { ok: false; error: string };

async function ipHashNow(): Promise<string> {
  return hashIp(clientIp(await headers()));
}

async function tooManyAttempts(ipHash: string): Promise<boolean> {
  const sql = await db();
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.login_attempts
    WHERE ip_hash = ${ipHash} AND scope = 'cliente' AND at > now() - make_interval(mins => ${LOCK_MINUTES})
  `;
  return count >= MAX_FAILED_LOGINS;
}

async function recordFailure(ipHash: string): Promise<void> {
  const sql = await db();
  await sql`INSERT INTO lotbot.login_attempts (ip_hash, scope) VALUES (${ipHash}, 'cliente')`;
  await new Promise((resolve) => setTimeout(resolve, 500));
}

const NOT_CONFIGURED = "Las cuentas de cliente no están disponibles todavía (falta SESSION_SECRET).";

export async function loginCustomer(email: string, password: string): Promise<AuthResult> {
  if (!accountsConfigured()) return { ok: false, error: NOT_CONFIGURED };
  const ipHash = await ipHashNow();
  if (await tooManyAttempts(ipHash)) {
    return { ok: false, error: `Demasiados intentos. Espera ${LOCK_MINUTES} minutos.` };
  }
  const sql = await db();
  const rows = await sql<{ id: number; password_hash: string | null; session_version: number }[]>`
    SELECT id, password_hash, session_version FROM lotbot.customers WHERE email = ${email.trim().toLowerCase()}
  `;
  const row = rows[0];
  // Se calcula siempre (aunque no exista) para no revelar qué emails son clientes.
  const ok = await verifyPassword(password, row?.password_hash ?? "scrypt$16384$8$1$AAAA$AAAA");
  if (!row || !ok) {
    await recordFailure(ipHash);
    return { ok: false, error: "Email o contraseña incorrectos." };
  }
  await startSession(row.id, row.session_version);
  return { ok: true };
}

/**
 * Crear la cuenta. Si el email ya es cliente (compró o pidió la prueba) pero
 * aún no tenía contraseña, hace falta una de sus claves de licencia: así nadie
 * puede quedarse con la cuenta de otro sabiendo solo su email.
 */
export async function registerCustomer(input: {
  email: string;
  name: string;
  password: string;
  licenseKey: string;
}): Promise<AuthResult & { needsKey?: boolean }> {
  if (!accountsConfigured()) return { ok: false, error: NOT_CONFIGURED };
  const problem = passwordProblem(input.password);
  if (problem) return { ok: false, error: problem };
  const ipHash = await ipHashNow();
  if (await tooManyAttempts(ipHash)) {
    return { ok: false, error: `Demasiados intentos. Espera ${LOCK_MINUTES} minutos.` };
  }
  const sql = await db();
  const email = input.email.trim().toLowerCase();
  const existing = await sql<{ id: number; password_hash: string | null }[]>`
    SELECT id, password_hash FROM lotbot.customers WHERE email = ${email}
  `;
  const hash = await hashPassword(input.password);
  if (existing.length) {
    const customer = existing[0];
    if (customer.password_hash) {
      return { ok: false, error: "Ya hay una cuenta con ese email. Entra con tu contraseña." };
    }
    const key = input.licenseKey.trim().toUpperCase();
    if (!key) {
      return {
        ok: false,
        needsKey: true,
        error: "Ese email ya es cliente de LOT Bot. Para crear tu cuenta, escribe también una de tus claves de licencia (LOTB-…).",
      };
    }
    const owns = await sql`SELECT 1 FROM lotbot.licenses WHERE key = ${key} AND customer_id = ${customer.id}`;
    if (!owns.length) {
      await recordFailure(ipHash);
      return { ok: false, needsKey: true, error: "Esa clave de licencia no es de este email." };
    }
    const [row] = await sql<{ session_version: number }[]>`
      UPDATE lotbot.customers SET password_hash = ${hash}, session_version = session_version + 1,
        name = CASE WHEN ${input.name} <> '' THEN ${input.name} ELSE name END
      WHERE id = ${customer.id} RETURNING session_version
    `;
    await logEvent("Cuenta de cliente creada (cliente existente)", email, "web");
    await startSession(customer.id, row.session_version);
    return { ok: true };
  }
  const [row] = await sql<{ id: number; session_version: number }[]>`
    INSERT INTO lotbot.customers (email, email_normalized, name, password_hash)
    VALUES (${email}, ${normalizeEmail(email)}, ${input.name}, ${hash})
    ON CONFLICT (email) DO NOTHING
    RETURNING id, session_version
  `;
  if (!row) return { ok: false, error: "Ya hay una cuenta con ese email. Entra con tu contraseña." };
  await logEvent("Cuenta de cliente creada", email, "web");
  await startSession(row.id, row.session_version);
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Enlaces de un solo uso (poner o cambiar la contraseña)
// ---------------------------------------------------------------------------
function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export async function createPasswordToken(customerId: number, hours = TOKEN_HOURS): Promise<string> {
  const token = randomBytes(24).toString("base64url");
  const sql = await db();
  await sql`
    INSERT INTO lotbot.password_tokens (token_hash, customer_id, expires_at)
    VALUES (${tokenHash(token)}, ${customerId}, now() + make_interval(hours => ${hours}))
  `;
  return token;
}

export async function tokenCustomer(token: string): Promise<{ id: number; email: string } | null> {
  if (!token) return null;
  const sql = await db();
  const rows = await sql<{ id: number; email: string }[]>`
    SELECT c.id, c.email FROM lotbot.password_tokens t JOIN lotbot.customers c ON c.id = t.customer_id
    WHERE t.token_hash = ${tokenHash(token)} AND t.used_at IS NULL AND t.expires_at > now()
  `;
  return rows[0] ?? null;
}

export async function setPasswordWithToken(token: string, password: string): Promise<AuthResult> {
  if (!accountsConfigured()) return { ok: false, error: NOT_CONFIGURED };
  const problem = passwordProblem(password);
  if (problem) return { ok: false, error: problem };
  const hash = await hashPassword(password);
  const sql = await db();
  const result = await sql.begin(async (tx) => {
    const [row] = await tx<{ customer_id: number }[]>`
      UPDATE lotbot.password_tokens SET used_at = now()
      WHERE token_hash = ${tokenHash(token)} AND used_at IS NULL AND expires_at > now()
      RETURNING customer_id
    `;
    if (!row) return null;
    const [customer] = await tx<{ id: number; session_version: number; email: string }[]>`
      UPDATE lotbot.customers SET password_hash = ${hash}, session_version = session_version + 1
      WHERE id = ${row.customer_id} RETURNING id, session_version, email
    `;
    return customer;
  });
  if (!result) return { ok: false, error: "El enlace ha caducado o ya se ha usado. Pide otro." };
  await logEvent("Contraseña de cliente puesta con enlace", result.email, "web");
  await startSession(result.id, result.session_version);
  return { ok: true };
}

export async function changePassword(customerId: number, current: string, next: string): Promise<AuthResult> {
  const problem = passwordProblem(next);
  if (problem) return { ok: false, error: problem };
  const sql = await db();
  const [row] = await sql<{ password_hash: string | null }[]>`
    SELECT password_hash FROM lotbot.customers WHERE id = ${customerId}
  `;
  if (!row || !(await verifyPassword(current, row.password_hash))) {
    return { ok: false, error: "La contraseña actual no es correcta." };
  }
  const [updated] = await sql<{ session_version: number }[]>`
    UPDATE lotbot.customers SET password_hash = ${await hashPassword(next)}, session_version = session_version + 1
    WHERE id = ${customerId} RETURNING session_version
  `;
  await startSession(customerId, updated.session_version);
  return { ok: true };
}
