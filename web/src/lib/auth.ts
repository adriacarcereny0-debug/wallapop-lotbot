/**
 * Acceso a /admin: una contraseña (ADMIN_PASSWORD) y una cookie firmada.
 * Tras varios intentos fallidos desde la misma conexión se bloquea un rato.
 */
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { db } from "./db";
import { TwoFactorUnreadable, twoFactorEnabled, verifyCode } from "./totp";
import { clientIp, hashIp, secret } from "./util";

const COOKIE = "lotbot_admin";
const SESSION_HOURS = 12;
export const MAX_FAILED_LOGINS = 5;
const LOCK_MINUTES = 15;

/** La firma depende también de la contraseña: al cambiar ADMIN_PASSWORD se
 * cierran todas las sesiones abiertas de /admin. */
function sign(payload: string): string {
  const password = createHash("sha256").update(process.env.ADMIN_PASSWORD ?? "").digest("hex");
  return createHmac("sha256", `admin|${secret()}|${password}`).update(payload).digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export function adminConfigured(): boolean {
  return (process.env.ADMIN_PASSWORD || "").length >= 8;
}

export async function isAdmin(): Promise<boolean> {
  if (!adminConfigured()) return false;
  const value = (await cookies()).get(COOKIE)?.value;
  if (!value) return false;
  const [expires, signature] = value.split(".");
  if (!expires || !signature || !safeEqual(sign(expires), signature)) return false;
  return Number(expires) > Date.now();
}

/** Para las páginas y acciones de /admin: fuera si no hay sesión. */
export async function requireAdmin(): Promise<void> {
  if (!(await isAdmin())) redirect("/admin/login");
}

export type LoginResult = { ok: true } | { ok: false; error: string };

export async function login(password: string, code = ""): Promise<LoginResult> {
  if (!adminConfigured()) {
    return { ok: false, error: "Falta ADMIN_PASSWORD (mínimo 8 caracteres) en las variables de Vercel." };
  }
  const ipHash = hashIp(clientIp(await headers()));
  const sql = await db();
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.login_attempts
    WHERE ip_hash = ${ipHash} AND scope = 'admin' AND at > now() - make_interval(mins => ${LOCK_MINUTES})
  `;
  if (count >= MAX_FAILED_LOGINS) {
    return { ok: false, error: `Demasiados intentos. Espera ${LOCK_MINUTES} minutos.` };
  }
  const expected = createHmac("sha256", "pw").update(process.env.ADMIN_PASSWORD as string).digest("hex");
  const given = createHmac("sha256", "pw").update(password).digest("hex");
  if (!safeEqual(expected, given)) {
    await sql`INSERT INTO lotbot.login_attempts (ip_hash) VALUES (${ipHash})`;
    await new Promise((resolve) => setTimeout(resolve, 600));
    return { ok: false, error: "Contraseña incorrecta." };
  }
  if (await twoFactorEnabled()) {
    if (!code.trim()) return { ok: false, error: "Escribe el código de 6 cifras de tu app de verificación." };
    let valid = false;
    try {
      valid = await verifyCode(code);
    } catch (error) {
      if (error instanceof TwoFactorUnreadable) return { ok: false, error: error.message };
      throw error;
    }
    if (!valid) {
      await sql`INSERT INTO lotbot.login_attempts (ip_hash) VALUES (${ipHash})`;
      return { ok: false, error: "Código de verificación incorrecto o ya usado." };
    }
  }
  await sql`DELETE FROM lotbot.login_attempts WHERE (ip_hash = ${ipHash} AND scope = 'admin') OR at < now() - interval '1 day'`;
  const expires = String(Date.now() + SESSION_HOURS * 3600 * 1000);
  (await cookies()).set(COOKIE, `${expires}.${sign(expires)}`, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/admin",
    maxAge: SESSION_HOURS * 3600,
  });
  await sql`INSERT INTO lotbot.events (actor, action, detail) VALUES ('admin', 'Entrada en /admin', '')`;
  return { ok: true };
}

export async function logout(): Promise<void> {
  (await cookies()).delete({ name: COOKIE, path: "/admin" });
}
