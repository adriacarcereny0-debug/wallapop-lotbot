import { NextResponse } from "next/server";

import { invalidRequest, parseLicenseRequest } from "@/lib/api";
import { db } from "@/lib/db";
import { authorizeDevice, HTTP_STATUS } from "@/lib/licensing";
import { cleanText } from "@/lib/util";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RESULTS = new Set(["correcta", "modificada"]);

/** LOT Bot cuenta si su instalación coincide con la oficial (solo informa). */
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
  const result = String(extra.result ?? "");
  if (!RESULTS.has(result)) return invalidRequest();
  const auth = await authorizeDevice(parsed.key, parsed.device.fingerprint, parsed.ipHash);
  if ("error" in auth) {
    return NextResponse.json(auth.error, { status: HTTP_STATUS[auth.error.code], headers: { "Cache-Control": "no-store" } });
  }
  const sql = await db();
  await sql`
    UPDATE lotbot.devices SET integrity = ${result}, integrity_at = now(),
      integrity_detail = ${cleanText(extra.detail, 300)}
    WHERE license_id = ${auth.license.id} AND fingerprint = ${parsed.device.fingerprint}
  `;
  return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
}
