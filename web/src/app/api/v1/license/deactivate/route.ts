import { NextResponse } from "next/server";

import { invalidRequest, parseLicenseRequest } from "@/lib/api";
import { HTTP_STATUS, deactivate } from "@/lib/licensing";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

/** El cliente libera este ordenador para usar la licencia en otro. */
export async function POST(request: Request) {
  const parsed = await parseLicenseRequest(request);
  if (!parsed) return invalidRequest();
  const result = await deactivate(parsed.key, parsed.device.fingerprint, parsed.ipHash);
  return NextResponse.json(result, {
    status: result.ok ? 200 : HTTP_STATUS[result.code],
    headers: { "Cache-Control": "no-store" },
  });
}
