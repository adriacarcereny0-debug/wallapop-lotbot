import { NextResponse } from "next/server";

import { registerRelease, releaseTokenOk, type ReleaseInput } from "@/lib/releases";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** GitHub Actions registra aquí cada versión publicada (con RELEASE_API_TOKEN). */
export async function POST(request: Request) {
  if (!releaseTokenOk(request.headers.get("authorization"))) {
    return NextResponse.json({ ok: false, error: "No autorizado." }, { status: 401 });
  }
  let body: ReleaseInput;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Datos no válidos." }, { status: 400 });
  }
  const result = await registerRelease(body);
  return NextResponse.json(result, { status: result.ok ? 200 : 400 });
}
