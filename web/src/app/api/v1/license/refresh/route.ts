import { invalidRequest, leaseResponse, parseLicenseRequest } from "@/lib/api";
import { refresh } from "@/lib/licensing";

export const dynamic = "force-dynamic";

/** LOT Bot renueva su pase (al abrir y cada pocas horas). */
export async function POST(request: Request) {
  const parsed = await parseLicenseRequest(request);
  if (!parsed) return invalidRequest();
  return leaseResponse(await refresh(parsed.key, parsed.device, parsed.ipHash));
}
