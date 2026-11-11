import { createHash, randomInt } from "node:crypto";

/** Letras y números sin los que se confunden (0/O, 1/I/L). */
const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

function randomBlock(length: number): string {
  let out = "";
  for (let i = 0; i < length; i++) out += ALPHABET[randomInt(ALPHABET.length)];
  return out;
}

/** Clave de licencia: LOTB-XXXX-XXXX-XXXX. */
export function newLicenseKey(): string {
  return `LOTB-${randomBlock(4)}-${randomBlock(4)}-${randomBlock(4)}`;
}

/** Referencia de pedido (va en el concepto de Bizum o transferencia). */
export function newOrderReference(): string {
  return `LOT-${randomBlock(8)}`;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function cleanEmail(raw: unknown): string | null {
  const email = String(raw ?? "").trim().toLowerCase();
  return email.length <= 200 && EMAIL_RE.test(email) ? email : null;
}

/**
 * Para la prueba de un solo uso: la misma bandeja de entrada cuenta como el
 * mismo email («juan.perez+2@gmail.com» = «juanperez@gmail.com»).
 */
export function normalizeEmail(email: string): string {
  const [local, domain] = email.toLowerCase().split("@");
  let user = local.split("+")[0];
  let host = domain;
  if (host === "googlemail.com") host = "gmail.com";
  if (host === "gmail.com") user = user.replace(/\./g, "");
  return `${user}@${host}`;
}

export function cleanText(raw: unknown, max = 200): string {
  return String(raw ?? "").replace(/\s+/g, " ").trim().slice(0, max);
}

export function secret(): string {
  return process.env.SESSION_SECRET || process.env.ADMIN_PASSWORD || "lotbot-sin-secreto";
}

/** La IP nunca se guarda tal cual: solo su huella (para limitar abusos). */
export function hashIp(ip: string): string {
  return createHash("sha256").update(`${ip}|${secret()}`).digest("hex").slice(0, 32);
}

export function clientIp(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for");
  return (forwarded?.split(",")[0] || headers.get("x-real-ip") || "desconocida").trim();
}

export function formatMoney(cents: number, currency = "EUR"): string {
  const value = cents / 100;
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency,
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
  }).format(value);
}

export function formatDate(value: Date | string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}

export function siteUrl(headers?: Headers): string {
  const configured = process.env.SITE_URL?.replace(/\/$/, "");
  if (configured) return configured;
  const host = headers?.get("x-forwarded-host") || headers?.get("host");
  if (host) return `${host.startsWith("localhost") ? "http" : "https"}://${host}`;
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return "http://localhost:3000";
}
