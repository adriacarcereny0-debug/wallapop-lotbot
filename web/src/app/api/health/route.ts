import { NextResponse } from "next/server";

import { db, hasDatabase } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!hasDatabase()) return NextResponse.json({ ok: false, database: "sin configurar" }, { status: 503 });
  try {
    const sql = await db();
    await sql`SELECT 1`;
    return NextResponse.json({ ok: true, database: "conectada" });
  } catch {
    return NextResponse.json({ ok: false, database: "error" }, { status: 503 });
  }
}
