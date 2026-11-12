import { NextResponse } from "next/server";

import { verifyLicense } from "@/lib/store";
import { cleanText } from "@/lib/util";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

/**
 * Para LOT Bot (escritorio): ¿es válida esta licencia en este ordenador?
 * POST { "key": "LOTB-XXXX-XXXX-XXXX", "deviceId": "..." }
 */
export async function POST(request: Request) {
  let body: Record<string, unknown> = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ valid: false, reason: "Datos no válidos." }, { status: 400 });
  }
  const key = cleanText(body.key, 40);
  if (!key) return NextResponse.json({ valid: false, reason: "Falta la clave." }, { status: 400 });
  const result = await verifyLicense(key, cleanText(body.deviceId, 120));
  return NextResponse.json(result);
}
