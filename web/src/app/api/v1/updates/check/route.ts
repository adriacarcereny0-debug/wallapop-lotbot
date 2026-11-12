import { NextResponse } from "next/server";

import { invalidRequest, parseLicenseRequest } from "@/lib/api";
import { authorizeDevice, HTTP_STATUS } from "@/lib/licensing";
import { checkForUpdate } from "@/lib/releases";
import { siteUrl } from "@/lib/util";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * LOT Bot pregunta si hay versión nueva:
 * { key, device: { fingerprint, app_version }, platform, channel }.
 * Solo contesta a licencias en uso en ese ordenador.
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
  const auth = await authorizeDevice(parsed.key, parsed.device.fingerprint, parsed.ipHash);
  if ("error" in auth) {
    return NextResponse.json(auth.error, { status: HTTP_STATUS[auth.error.code], headers: { "Cache-Control": "no-store" } });
  }
  const offer = await checkForUpdate({
    licenseId: auth.license.id,
    fingerprint: parsed.device.fingerprint,
    platform: String(extra.platform ?? ""),
    channel: String(extra.channel ?? "estable"),
    current: parsed.device.appVersion ?? "",
    baseUrl: siteUrl(request.headers),
  });
  return NextResponse.json({ ok: true, update: offer }, { headers: { "Cache-Control": "no-store" } });
}
