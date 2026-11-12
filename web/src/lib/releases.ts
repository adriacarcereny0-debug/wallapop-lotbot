/**
 * Versiones del programa y actualizaciones automáticas.
 *
 * - GitHub Actions compila cada versión (Windows y Mac), la prueba, la publica
 *   en GitHub y la registra aquí (`registerRelease`, con RELEASE_API_TOKEN).
 * - LOT Bot pregunta con su licencia (`checkForUpdate`). Solo las licencias
 *   activas reciben la actualización. La respuesta lleva un pase FIRMADO con
 *   la versión y la huella SHA-256 del instalador: LOT Bot no instala nada
 *   que no cuadre con ese pase.
 * - La descarga pasa por aquí (`/api/v1/updates/download`) con un enlace que
 *   caduca en 30 minutos; el instalador puede estar en un repositorio privado.
 * - Despliegue gradual: cada ordenador cae siempre en el mismo «grupo» (0-99)
 *   para cada versión; si el grupo es menor que el porcentaje, la recibe.
 */
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

import { db, logEvent } from "./db";
import { signUpdate } from "./signing";
import { secret } from "./util";

export const PLATFORMS = ["windows-x64", "mac-arm64", "mac-intel"] as const;
export type Platform = (typeof PLATFORMS)[number];
export const CHANNELS = ["estable", "beta"] as const;
const VERSION_RE = /^\d{1,4}\.\d{1,4}\.\d{1,4}$/;
const DOWNLOAD_MINUTES = 30;

export type Release = {
  id: number;
  version: string;
  platform: Platform;
  channel: string;
  asset_name: string;
  github_asset_id: string | null;
  download_url: string;
  sha256: string;
  size: string;
  notes: string;
  rollout_percent: number;
  mandatory: boolean;
  status: string;
  created_at: Date;
};

export function parseVersion(value: string): number[] | null {
  return VERSION_RE.test(value) ? value.split(".").map(Number) : null;
}

export function compareVersions(a: string, b: string): number {
  const x = parseVersion(a) ?? [0, 0, 0];
  const y = parseVersion(b) ?? [0, 0, 0];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

/** Grupo fijo (0-99) de un ordenador para una versión. */
export function rolloutBucket(fingerprint: string, version: string): number {
  return createHash("sha256").update(`${fingerprint}|${version}`).digest().readUInt32BE(0) % 100;
}

// ---------------------------------------------------------------------------
// Registrar (GitHub Actions)
// ---------------------------------------------------------------------------
export function releaseTokenOk(header: string | null): boolean {
  const expected = process.env.RELEASE_API_TOKEN ?? "";
  const given = (header ?? "").replace(/^Bearer\s+/i, "");
  if (expected.length < 24 || !given) return false;
  const a = Buffer.from(createHash("sha256").update(expected).digest("hex"));
  const b = Buffer.from(createHash("sha256").update(given).digest("hex"));
  return timingSafeEqual(a, b);
}

export type ReleaseInput = {
  version: string;
  channel?: string;
  notes?: string;
  rollout_percent?: number;
  mandatory?: boolean;
  assets: { platform: string; name: string; sha256: string; size: number; github_asset_id?: number | null; url?: string }[];
};

export async function registerRelease(input: ReleaseInput): Promise<{ ok: true; ids: number[] } | { ok: false; error: string }> {
  const sort = parseVersion(String(input.version ?? ""));
  if (!sort) return { ok: false, error: "Versión no válida (formato 1.2.3)." };
  const channel = input.channel ?? "estable";
  if (!CHANNELS.includes(channel as never)) return { ok: false, error: "Canal no válido." };
  if (!Array.isArray(input.assets) || !input.assets.length) return { ok: false, error: "Faltan los instaladores." };
  const rollout = Math.max(0, Math.min(100, Math.round(Number(input.rollout_percent ?? 100))));
  for (const asset of input.assets) {
    if (!PLATFORMS.includes(asset.platform as Platform)) return { ok: false, error: `Plataforma no válida: ${asset.platform}` };
    if (!/^[0-9a-f]{64}$/.test(String(asset.sha256))) return { ok: false, error: "SHA-256 no válido." };
    if (!(Number(asset.size) > 0)) return { ok: false, error: "Tamaño no válido." };
    if (!asset.github_asset_id && !/^https:\/\//.test(asset.url ?? "")) {
      return { ok: false, error: "Cada instalador necesita github_asset_id o una url https." };
    }
  }
  const sql = await db();
  const ids: number[] = [];
  for (const asset of input.assets) {
    const [row] = await sql<{ id: number }[]>`
      INSERT INTO lotbot.releases (version, version_sort, platform, channel, asset_name, github_asset_id,
        download_url, sha256, size, notes, rollout_percent, mandatory)
      VALUES (${input.version}, ${sort}, ${asset.platform}, ${channel}, ${String(asset.name).slice(0, 200)},
        ${asset.github_asset_id ?? null}, ${asset.url ?? ""}, ${asset.sha256}, ${Number(asset.size)},
        ${String(input.notes ?? "").slice(0, 8000)}, ${rollout}, ${Boolean(input.mandatory)})
      ON CONFLICT (version, platform, channel) DO UPDATE SET
        asset_name = EXCLUDED.asset_name, github_asset_id = EXCLUDED.github_asset_id,
        download_url = EXCLUDED.download_url, sha256 = EXCLUDED.sha256, size = EXCLUDED.size,
        notes = EXCLUDED.notes
      RETURNING id
    `;
    ids.push(row.id);
  }
  await logEvent("Versión registrada", `${input.version} (${channel}) · ${input.assets.map((a) => a.platform).join(", ")}`, "github");
  return { ok: true, ids };
}

// ---------------------------------------------------------------------------
// Buscar actualización (LOT Bot)
// ---------------------------------------------------------------------------
export type UpdateOffer = {
  version: string;
  notes: string;
  mandatory: boolean;
  size: number;
  sha256: string;
  token: string;
  download: string;
};

export async function checkForUpdate(input: {
  licenseId: number;
  fingerprint: string;
  platform: string;
  channel: string;
  current: string;
  baseUrl: string;
}): Promise<UpdateOffer | null> {
  if (!PLATFORMS.includes(input.platform as Platform) || !parseVersion(input.current)) return null;
  const channels = input.channel === "beta" ? ["estable", "beta"] : ["estable"];
  const sql = await db();
  const rows = await sql<Release[]>`
    SELECT * FROM lotbot.releases
    WHERE platform = ${input.platform} AND channel IN ${sql(channels)} AND status = 'activa'
      AND version_sort > ${parseVersion(input.current) as number[]}
    ORDER BY version_sort DESC
  `;
  // ¿Hay alguna obligatoria por encima de la suya? Entonces no espera turno.
  const mandatory = rows.some((r) => r.mandatory);
  const chosen = rows.find((r) => mandatory || rolloutBucket(input.fingerprint, r.version) < r.rollout_percent);
  if (!chosen) return null;
  const now = Math.floor(Date.now() / 1000);
  const token = signUpdate({
    ver: chosen.version,
    plat: chosen.platform,
    sha256: chosen.sha256,
    size: Number(chosen.size),
    mandatory,
    dev: input.fingerprint,
    iat: now,
    exp: now + 24 * 3600,
  });
  return {
    version: chosen.version,
    notes: chosen.notes,
    mandatory,
    size: Number(chosen.size),
    sha256: chosen.sha256,
    token,
    download: `${input.baseUrl}/api/v1/updates/download?t=${downloadTicket(chosen.id, input.licenseId)}`,
  };
}

// ---------------------------------------------------------------------------
// Descargar
// ---------------------------------------------------------------------------
function ticketSignature(body: string): string {
  return createHmac("sha256", `descarga|${secret()}`).update(body).digest("base64url");
}

export function downloadTicket(releaseId: number, licenseId: number): string {
  const expires = Math.floor(Date.now() / 1000) + DOWNLOAD_MINUTES * 60;
  const body = `${releaseId}.${licenseId}.${expires}`;
  return `${body}.${ticketSignature(body)}`;
}

export function readTicket(ticket: string): { releaseId: number; licenseId: number } | null {
  const parts = (ticket ?? "").split(".");
  if (parts.length !== 4) return null;
  const body = parts.slice(0, 3).join(".");
  const expected = Buffer.from(ticketSignature(body));
  const given = Buffer.from(parts[3]);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) return null;
  if (Number(parts[2]) < Date.now() / 1000) return null;
  return { releaseId: Number(parts[0]), licenseId: Number(parts[1]) };
}

/** Dónde descargar de verdad: GitHub (repositorio privado) o la url guardada. */
export async function resolveDownload(release: Release): Promise<string | null> {
  const repo = process.env.GITHUB_RELEASES_REPO;
  const token = process.env.GITHUB_RELEASES_TOKEN;
  if (release.github_asset_id && repo && token) {
    const response = await fetch(`https://api.github.com/repos/${repo}/releases/assets/${release.github_asset_id}`, {
      headers: {
        Accept: "application/octet-stream",
        Authorization: `Bearer ${token}`,
        "User-Agent": "lotbot-web",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      redirect: "manual",
    });
    const location = response.headers.get("location");
    if (response.status >= 300 && response.status < 400 && location) return location;
    console.error("GitHub no ha dado la descarga:", response.status);
  }
  return release.download_url || null;
}
