import { invalidRequest, leaseResponse, parseLicenseRequest } from "@/lib/api";
import { refresh } from "@/lib/licensing";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

/** LOT Bot renueva su pase (al abrir y cada pocas horas). */
export async function POST(request: Request) {
  const parsed = await parseLicenseRequest(request);
  if (!parsed) return invalidRequest();
  return leaseResponse(await refresh(parsed.key, parsed.device, parsed.ipHash));
}
