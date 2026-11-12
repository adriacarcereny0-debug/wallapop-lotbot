import { NextResponse } from "next/server";

import { invalidRequest, parseLicenseRequest } from "@/lib/api";
import { db } from "@/lib/db";
import { authorizeDevice, HTTP_STATUS } from "@/lib/licensing";
import { PLATFORMS } from "@/lib/releases";
import { signIntegrity } from "@/lib/signing";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * Huellas oficiales de los ficheros de la versión que tiene instalada este
 * ordenador, firmadas. { key, device: { fingerprint, app_version }, platform }.
 */
export async function POST(request: Request) {
  const copy = request.clone();
  const parsed = await parseLicenseRequest(request);
  if (!parsed) return invalidRequest();
  let extra: Record<string, unknown> = {};
  try {
    extra = await copy.json();
  } catch {
    return invalidRequest();
  }
  const platform = String(extra.platform ?? "");
  if (!PLATFORMS.includes(platform as never)) return invalidRequest();
  const auth = await authorizeDevice(parsed.key, parsed.device.fingerprint, parsed.ipHash);
  if ("error" in auth) {
    return NextResponse.json(auth.error, { status: HTTP_STATUS[auth.error.code], headers: { "Cache-Control": "no-store" } });
  }
  const sql = await db();
  const [release] = await sql<{ version: string; manifest: Record<string, string> }[]>`
    SELECT version, manifest FROM lotbot.releases
    WHERE version = ${parsed.device.appVersion ?? ""} AND platform = ${platform} AND manifest <> '{}'::jsonb
    ORDER BY (channel = 'estable') DESC LIMIT 1
  `;
  if (!release) return NextResponse.json({ ok: true, token: null }, { headers: { "Cache-Control": "no-store" } });
  const now = Math.floor(Date.now() / 1000);
  const token = signIntegrity({
    ver: release.version,
    plat: platform,
    files: release.manifest,
    dev: parsed.device.fingerprint,
    iat: now,
    exp: now + 24 * 3600,
  });
  return NextResponse.json({ ok: true, token }, { headers: { "Cache-Control": "no-store" } });
}
