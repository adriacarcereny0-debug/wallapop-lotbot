import { NextResponse } from "next/server";

import { db } from "@/lib/db";
import { readTicket, resolveDownload, type Release } from "@/lib/releases";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Descarga del instalador con un enlace que caduca en 30 minutos. */
export async function GET(request: Request) {
  const ticket = readTicket(new URL(request.url).searchParams.get("t") ?? "");
  if (!ticket) return NextResponse.json({ ok: false, error: "Enlace caducado o no válido." }, { status: 403 });
  const sql = await db();
  const [release] = await sql<Release[]>`
    SELECT r.* FROM lotbot.releases r WHERE r.id = ${ticket.releaseId} AND r.status = 'activa'
  `;
  const [license] = await sql<{ status: string; expires_at: Date | null }[]>`
    SELECT status, expires_at FROM lotbot.licenses WHERE id = ${ticket.licenseId}
  `;
  if (!release || !license || license.status !== "activa" || (license.expires_at && new Date(license.expires_at) <= new Date())) {
    return NextResponse.json({ ok: false, error: "Esta descarga ya no está disponible." }, { status: 403 });
  }
  const location = await resolveDownload(release);
  if (!location) return NextResponse.json({ ok: false, error: "Descarga no disponible ahora mismo." }, { status: 503 });
  return NextResponse.redirect(location, { status: 302, headers: { "Cache-Control": "no-store" } });
}
