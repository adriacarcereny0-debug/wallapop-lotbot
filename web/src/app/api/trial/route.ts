import { NextResponse } from "next/server";

import { startTrial } from "@/lib/store";
import { cleanEmail, cleanText, clientIp, hashIp } from "@/lib/util";

export const dynamic = "force-dynamic";

/** Prueba gratis de un solo uso: devuelve la clave de 24 h. */
export async function POST(request: Request) {
  let body: Record<string, unknown> = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Datos no válidos." }, { status: 400 });
  }
  if (cleanText(body.website)) {
    // Campo trampa invisible: solo lo rellenan los robots.
    return NextResponse.json({ ok: false, error: "Datos no válidos." }, { status: 400 });
  }
  const email = cleanEmail(body.email);
  if (!email) return NextResponse.json({ ok: false, error: "Escribe un email válido." }, { status: 400 });
  if (body.accept !== true) {
    return NextResponse.json({ ok: false, error: "Acepta la política de privacidad para continuar." }, { status: 400 });
  }
  const deviceId = cleanText(body.deviceId, 120) || null;
  try {
    const result = await startTrial({
      email,
      name: cleanText(body.name, 120),
      phone: cleanText(body.phone, 40),
      ipHash: hashIp(clientIp(request.headers)),
      deviceId,
    });
    return NextResponse.json(result, { status: result.ok ? 200 : 409 });
  } catch (error) {
    console.error("Prueba gratis:", error);
    return NextResponse.json({ ok: false, error: "No se ha podido crear la prueba. Inténtalo de nuevo." }, { status: 500 });
  }
}
