import { NextResponse } from "next/server";

import { SCHEMA_VERSION, db, hasDatabase } from "@/lib/db";
import { currentKeyId, signingConfigured } from "@/lib/signing";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

export async function GET() {
  if (!hasDatabase()) return NextResponse.json({ ok: false, database: "sin configurar" }, { status: 503 });
  try {
    const sql = await db();
    await sql`SELECT 1`;
    return NextResponse.json({
      ok: true,
      database: "conectada",
      schema: SCHEMA_VERSION,
      licensing: signingConfigured() ? { signing: "configurada", kid: currentKeyId() } : { signing: "falta" },
    });
  } catch {
    return NextResponse.json({ ok: false, database: "error" }, { status: 503 });
  }
}
