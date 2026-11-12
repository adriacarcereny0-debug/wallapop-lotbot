import { invalidRequest, leaseResponse, parseLicenseRequest } from "@/lib/api";
import { activate } from "@/lib/licensing";

export const dynamic = "force-dynamic";
// Firma Ed25519 y Postgres: necesitan Node.js (no el entorno «edge»).
export const runtime = "nodejs";

/** LOT Bot activa este ordenador con su clave y recibe un pase firmado. */
export async function POST(request: Request) {
  const parsed = await parseLicenseRequest(request);
  if (!parsed) return invalidRequest();
  return leaseResponse(await activate(parsed.key, parsed.device, parsed.ipHash));
}
