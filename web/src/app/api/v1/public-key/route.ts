import { NextResponse } from "next/server";

import { currentKeyId, publicKeyBase64 } from "@/lib/signing";

export const dynamic = "force-dynamic";

/** Clave PÚBLICA con la que LOT Bot comprueba los pases (no es secreta). */
export async function GET() {
  const key = publicKeyBase64();
  if (!key) return NextResponse.json({ ok: false, message: "Sin clave de firma." }, { status: 503 });
  return NextResponse.json({ ok: true, algorithm: "Ed25519", kid: currentKeyId(), public_key: key });
}
