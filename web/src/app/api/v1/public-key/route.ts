import { NextResponse } from "next/server";

import { currentKeyId, publicKeyBase64 } from "@/lib/signing";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

/** Clave PÚBLICA con la que LOT Bot comprueba los pases (no es secreta). */
export async function GET() {
  const key = publicKeyBase64();
  if (!key) return NextResponse.json({ ok: false, message: "Sin clave de firma." }, { status: 503 });
  return NextResponse.json({ ok: true, algorithm: "Ed25519", kid: currentKeyId(), public_key: key });
}
