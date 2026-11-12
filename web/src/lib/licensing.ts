/**
 * Licencias de LOT Bot: activar un ordenador, renovar su «pase» y liberarlo.
 *
 * Reglas (decididas):
 *  - Cada licencia admite N ordenadores (mensual 1, anual 2; lo dice el plan).
 *  - El pase firmado dura 72 h (margen sin conexión de 3 días) y nunca más
 *    allá de la fecha de fin de la licencia.
 *  - Una licencia suspendida o revocada deja de renovar: LOT Bot se bloquea
 *    en cuanto caduca su pase (o antes, si consigue preguntar al servidor).
 *  - La prueba gratis es de un solo uso también por ordenador.
 *  - Freno a los intentos masivos de adivinar claves y a cambiar de
 *    ordenador una y otra vez para compartir la licencia.
 */
import { db } from "./db";
import { keyHash, signLease, signingConfigured } from "./signing";

/** Margen sin conexión: lo que dura un pase. */
export const LEASE_HOURS = Number(process.env.LICENSE_LEASE_HOURS) || 72;
/** Intentos fallidos (clave inexistente) por conexión y hora. */
export const MAX_FAILED_PER_HOUR = 20;
/** Cambios de ordenador que el propio cliente puede hacer cada 30 días. */
export const MAX_SELF_DEACTIVATIONS_PER_MONTH = 3;
/** Activaciones nuevas por licencia y día (más = sospechoso de compartirla). */
export const MAX_ACTIVATIONS_PER_DAY = 6;

export type ErrorCode =
  | "INVALID_REQUEST"
  | "LICENSE_NOT_FOUND"
  | "LICENSE_EXPIRED"
  | "LICENSE_SUSPENDED"
  | "LICENSE_REVOKED"
  | "DEVICE_LIMIT"
  | "DEVICE_BLOCKED"
  | "DEVICE_NOT_ACTIVATED"
  | "TRIAL_ALREADY_USED"
  | "TOO_MANY_CHANGES"
  | "RATE_LIMITED"
  | "SERVER_NOT_CONFIGURED";

export const HTTP_STATUS: Record<ErrorCode, number> = {
  INVALID_REQUEST: 400,
  LICENSE_NOT_FOUND: 404,
  LICENSE_EXPIRED: 403,
  LICENSE_SUSPENDED: 403,
  LICENSE_REVOKED: 403,
  DEVICE_LIMIT: 409,
  DEVICE_BLOCKED: 403,
  DEVICE_NOT_ACTIVATED: 403,
  TRIAL_ALREADY_USED: 409,
  TOO_MANY_CHANGES: 429,
  RATE_LIMITED: 429,
  SERVER_NOT_CONFIGURED: 503,
};

export type LicenseInfo = {
  kind: string;
  plan: string | null;
  status: string;
  expires_at: string | null;
  max_devices: number;
  devices_in_use: number;
};

export type LeaseResult =
  | { ok: true; token: string; lease_expires_at: string; server_time: string; license: LicenseInfo }
  | { ok: false; code: ErrorCode; message: string; license?: LicenseInfo };

export type DeviceInput = {
  fingerprint: string;
  name?: string;
  os?: string;
  appVersion?: string;
};

type LicenseRow = {
  id: number;
  key: string;
  kind: string;
  status: string;
  status_reason: string;
  expires_at: Date | null;
  max_devices: number;
  plan_slug: string | null;
};

const FINGERPRINT_RE = /^[A-Za-z0-9_-]{16,128}$/;
export const KEY_RE = /^LOTB-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;

export function validFingerprint(value: string): boolean {
  return FINGERPRINT_RE.test(value);
}

export function normalizeKey(value: string): string {
  return value.trim().toUpperCase();
}

function fail(code: ErrorCode, message: string, license?: LicenseInfo): LeaseResult {
  return { ok: false, code, message, license };
}

async function record(licenseId: number | null, kind: string, fingerprint = "", ipHash = "", detail = "") {
  const sql = await db();
  await sql`
    INSERT INTO lotbot.license_events (license_id, kind, fingerprint, ip_hash, detail)
    VALUES (${licenseId}, ${kind}, ${fingerprint}, ${ipHash}, ${detail.slice(0, 500)})
  `;
}

async function tooManyFailures(ipHash: string): Promise<boolean> {
  const sql = await db();
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.license_events
    WHERE ip_hash = ${ipHash} AND kind = 'clave_inexistente' AND at > now() - interval '1 hour'
  `;
  return count >= MAX_FAILED_PER_HOUR;
}

async function findLicense(key: string): Promise<LicenseRow | null> {
  const sql = await db();
  const rows = await sql<LicenseRow[]>`
    SELECT l.id, l.key, l.kind, l.status, l.status_reason, l.expires_at, l.max_devices, p.slug AS plan_slug
    FROM lotbot.licenses l LEFT JOIN lotbot.plans p ON p.id = l.plan_id
    WHERE l.key = ${key}
  `;
  return rows[0] ?? null;
}

async function info(license: LicenseRow): Promise<LicenseInfo> {
  const sql = await db();
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.devices WHERE license_id = ${license.id} AND status = 'activo'
  `;
  return {
    kind: license.kind,
    plan: license.plan_slug,
    status: license.status,
    expires_at: license.expires_at ? new Date(license.expires_at).toISOString() : null,
    max_devices: license.max_devices,
    devices_in_use: count,
  };
}

/** ¿Se puede usar la licencia ahora? null = sí; si no, el motivo. */
function unusable(license: LicenseRow, details: LicenseInfo): LeaseResult | null {
  if (license.status === "revocada") {
    return fail("LICENSE_REVOKED", "Esta licencia ha sido revocada.", details);
  }
  if (license.status === "suspendida") {
    const why = license.status_reason ? ` (${license.status_reason})` : "";
    return fail("LICENSE_SUSPENDED", `Esta licencia está suspendida${why}.`, details);
  }
  if (license.expires_at && new Date(license.expires_at) <= new Date()) {
    return fail(
      "LICENSE_EXPIRED",
      license.kind === "prueba" ? "La prueba gratis ha terminado." : "La licencia ha caducado.",
      details,
    );
  }
  return null;
}

function issue(license: LicenseRow, fingerprint: string, details: LicenseInfo): LeaseResult {
  const now = Date.now();
  let exp = now + LEASE_HOURS * 3600 * 1000;
  if (license.expires_at) exp = Math.min(exp, new Date(license.expires_at).getTime());
  const token = signLease({
    lic: license.id,
    kh: keyHash(license.key),
    dev: fingerprint,
    kind: license.kind,
    plan: license.plan_slug,
    seats: license.max_devices,
    lic_exp: license.expires_at ? Math.floor(new Date(license.expires_at).getTime() / 1000) : null,
    iat: Math.floor(now / 1000),
    exp: Math.floor(exp / 1000),
  });
  return {
    ok: true,
    token,
    lease_expires_at: new Date(exp).toISOString(),
    server_time: new Date(now).toISOString(),
    license: details,
  };
}

async function preflight(rawKey: string, fingerprint: string, ipHash: string) {
  if (!signingConfigured()) {
    return { error: fail("SERVER_NOT_CONFIGURED", "El servidor de licencias no está configurado.") };
  }
  const key = normalizeKey(rawKey);
  if (!KEY_RE.test(key) || !validFingerprint(fingerprint)) {
    return { error: fail("INVALID_REQUEST", "Clave u ordenador no válidos.") };
  }
  if (await tooManyFailures(ipHash)) {
    return { error: fail("RATE_LIMITED", "Demasiados intentos. Espera una hora y vuelve a probar.") };
  }
  const license = await findLicense(key);
  if (!license) {
    await record(null, "clave_inexistente", fingerprint, ipHash);
    return { error: fail("LICENSE_NOT_FOUND", "Esa clave de licencia no existe.") };
  }
  return { license };
}

/** Desde qué conexiones (huella de la IP, nunca la IP) se usa cada licencia, por día. */
async function noteConnection(licenseId: number, ipHash: string): Promise<void> {
  if (!ipHash) return;
  const sql = await db();
  await sql`
    INSERT INTO lotbot.license_connections (license_id, ip_hash, day, checks)
    VALUES (${licenseId}, ${ipHash}, current_date, 1)
    ON CONFLICT (license_id, ip_hash, day) DO UPDATE SET checks = license_connections.checks + 1
  `;
}

/** Activa LOT Bot en un ordenador (o lo reactiva si ya estaba). */
export async function activate(rawKey: string, device: DeviceInput, ipHash: string): Promise<LeaseResult> {
  const checked = await preflight(rawKey, device.fingerprint, ipHash);
  if ("error" in checked) return checked.error as LeaseResult;
  const license = checked.license;
  const sql = await db();
  const details = await info(license);
  const problem = unusable(license, details);
  if (problem) {
    await record(license.id, "activacion_rechazada", device.fingerprint, ipHash, problem.ok ? "" : problem.code);
    return problem;
  }
  const result = await sql.begin(async (tx) => {
    // Bloqueo de la licencia: dos activaciones a la vez no se saltan el límite.
    await tx`SELECT id FROM lotbot.licenses WHERE id = ${license.id} FOR UPDATE`;
    const [existing] = await tx<{ id: number; status: string }[]>`
      SELECT id, status FROM lotbot.devices WHERE license_id = ${license.id} AND fingerprint = ${device.fingerprint}
    `;
    if (existing?.status === "bloqueado") {
      return fail("DEVICE_BLOCKED", "Este ordenador está bloqueado para esta licencia. Contacta con soporte.");
    }
    if (license.kind === "prueba") {
      const other = await tx`
        SELECT 1 FROM lotbot.devices d JOIN lotbot.licenses l ON l.id = d.license_id
        WHERE d.fingerprint = ${device.fingerprint} AND l.kind = 'prueba' AND l.id <> ${license.id}
        LIMIT 1
      `;
      if (other.length) {
        return fail("TRIAL_ALREADY_USED", "Este ordenador ya ha usado la prueba gratis. Elige un plan para seguir.");
      }
    }
    if (existing?.status !== "activo") {
      const [{ count }] = await tx<{ count: number }[]>`
        SELECT count(*)::int AS count FROM lotbot.devices WHERE license_id = ${license.id} AND status = 'activo'
      `;
      if (count >= license.max_devices) {
        return fail(
          "DEVICE_LIMIT",
          `Esta licencia ya está activada en ${count} ordenador(es) (máximo ${license.max_devices}). ` +
            "Desvincula uno desde tu cuenta para usarla aquí.",
          { ...details, devices_in_use: count },
        );
      }
      const [{ today }] = await tx<{ today: number }[]>`
        SELECT count(*)::int AS today FROM lotbot.license_events
        WHERE license_id = ${license.id} AND kind = 'activacion' AND at > now() - interval '1 day'
      `;
      if (today >= MAX_ACTIVATIONS_PER_DAY) {
        return fail("TOO_MANY_CHANGES", "Demasiadas activaciones hoy con esta licencia. Inténtalo mañana o contacta con soporte.");
      }
    }
    await tx`
      INSERT INTO lotbot.devices (license_id, fingerprint, name, os, app_version, last_ip_hash, status)
      VALUES (${license.id}, ${device.fingerprint}, ${(device.name ?? "").slice(0, 80)},
              ${(device.os ?? "").slice(0, 60)}, ${(device.appVersion ?? "").slice(0, 30)}, ${ipHash}, 'activo')
      ON CONFLICT (license_id, fingerprint) DO UPDATE SET
        status = 'activo', last_seen = now(), last_ip_hash = EXCLUDED.last_ip_hash,
        name = CASE WHEN EXCLUDED.name <> '' THEN EXCLUDED.name ELSE devices.name END,
        os = CASE WHEN EXCLUDED.os <> '' THEN EXCLUDED.os ELSE devices.os END,
        app_version = CASE WHEN EXCLUDED.app_version <> '' THEN EXCLUDED.app_version ELSE devices.app_version END
    `;
    if (existing?.status !== "activo") {
      await tx`
        INSERT INTO lotbot.license_events (license_id, kind, fingerprint, ip_hash, detail)
        VALUES (${license.id}, 'activacion', ${device.fingerprint}, ${ipHash}, ${(device.name ?? "").slice(0, 80)})
      `;
    }
    return null;
  });
  if (result) return result;
  await noteConnection(license.id, ipHash);
  return issue(license, device.fingerprint, await info(license));
}

/** Renueva el pase de un ordenador ya activado (LOT Bot lo pide cada pocas horas). */
export async function refresh(rawKey: string, device: DeviceInput, ipHash: string): Promise<LeaseResult> {
  const checked = await preflight(rawKey, device.fingerprint, ipHash);
  if ("error" in checked) return checked.error as LeaseResult;
  const license = checked.license;
  const sql = await db();
  const details = await info(license);
  const [existing] = await sql<{ status: string }[]>`
    SELECT status FROM lotbot.devices WHERE license_id = ${license.id} AND fingerprint = ${device.fingerprint}
  `;
  if (existing?.status === "bloqueado") {
    return fail("DEVICE_BLOCKED", "Este ordenador está bloqueado para esta licencia. Contacta con soporte.", details);
  }
  if (existing?.status !== "activo") {
    return fail("DEVICE_NOT_ACTIVATED", "Este ordenador ya no está activado con esta licencia. Vuelve a activarla.", details);
  }
  const problem = unusable(license, details);
  if (problem) return problem;
  await sql`
    UPDATE lotbot.devices SET last_seen = now(), last_ip_hash = ${ipHash},
      app_version = CASE WHEN ${device.appVersion ?? ""} <> '' THEN ${device.appVersion ?? ""} ELSE app_version END
    WHERE license_id = ${license.id} AND fingerprint = ${device.fingerprint}
  `;
  await noteConnection(license.id, ipHash);
  return issue(license, device.fingerprint, details);
}

/**
 * Para pedir actualizaciones: la licencia tiene que estar en uso en ESTE
 * ordenador (activado, no bloqueado, ni caducada, suspendida o revocada).
 */
export async function authorizeDevice(
  rawKey: string,
  fingerprint: string,
  ipHash: string,
): Promise<{ license: { id: number; key: string } } | { error: Extract<LeaseResult, { ok: false }> }> {
  const checked = await preflight(rawKey, fingerprint, ipHash);
  if ("error" in checked) return { error: checked.error as Extract<LeaseResult, { ok: false }> };
  const license = checked.license;
  const sql = await db();
  const [device] = await sql<{ status: string }[]>`
    SELECT status FROM lotbot.devices WHERE license_id = ${license.id} AND fingerprint = ${fingerprint}
  `;
  if (device?.status === "bloqueado") {
    return { error: fail("DEVICE_BLOCKED", "Este ordenador está bloqueado para esta licencia.") as Extract<LeaseResult, { ok: false }> };
  }
  if (device?.status !== "activo") {
    return { error: fail("DEVICE_NOT_ACTIVATED", "Este ordenador no está activado con esta licencia.") as Extract<LeaseResult, { ok: false }> };
  }
  const problem = unusable(license, await info(license));
  if (problem) return { error: problem as Extract<LeaseResult, { ok: false }> };
  return { license: { id: license.id, key: license.key } };
}

export type DeactivateResult = { ok: true } | { ok: false; code: ErrorCode; message: string };

/** El cliente libera este ordenador (para usar la licencia en otro). */
export async function deactivate(rawKey: string, fingerprint: string, ipHash: string): Promise<DeactivateResult> {
  const checked = await preflight(rawKey, fingerprint, ipHash);
  if ("error" in checked) {
    const error = checked.error as Extract<LeaseResult, { ok: false }>;
    return { ok: false, code: error.code, message: error.message };
  }
  const license = checked.license;
  const sql = await db();
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.license_events
    WHERE license_id = ${license.id} AND kind = 'desvinculado_por_cliente' AND at > now() - interval '30 days'
  `;
  if (count >= MAX_SELF_DEACTIVATIONS_PER_MONTH) {
    return {
      ok: false,
      code: "TOO_MANY_CHANGES",
      message: `Solo puedes cambiar de ordenador ${MAX_SELF_DEACTIVATIONS_PER_MONTH} veces al mes. Contacta con soporte.`,
    };
  }
  const rows = await sql`
    UPDATE lotbot.devices SET status = 'desvinculado'
    WHERE license_id = ${license.id} AND fingerprint = ${fingerprint} AND status = 'activo'
    RETURNING id
  `;
  if (!rows.length) return { ok: false, code: "DEVICE_NOT_ACTIVATED", message: "Este ordenador no estaba activado." };
  await record(license.id, "desvinculado_por_cliente", fingerprint, ipHash);
  return { ok: true };
}
