import { NextResponse } from "next/server";

import { recordUnknownKey, tooManyFailures, validFingerprint } from "@/lib/licensing";
import { verifyLicense } from "@/lib/store";
import { cleanText, clientIp, hashIp } from "@/lib/util";

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
  const deviceId = cleanText(body.deviceId, 120);
  // Mismas protecciones que la API v1: huella de ordenador válida y freno a
  // quien prueba claves inventadas desde la misma conexión.
  if (deviceId && !validFingerprint(deviceId)) {
    return NextResponse.json({ valid: false, reason: "Ordenador no válido." }, { status: 400 });
  }
  const ipHash = hashIp(clientIp(request.headers));
  if (await tooManyFailures(ipHash)) {
    return NextResponse.json({ valid: false, reason: "Demasiados intentos. Espera una hora." }, { status: 429 });
  }
  const result = await verifyLicense(key, deviceId);
  if (!result.valid && result.reason === "La clave no existe.") await recordUnknownKey(deviceId, ipHash);
  return NextResponse.json(result);
}
