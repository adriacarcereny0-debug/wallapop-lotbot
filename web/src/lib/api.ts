import { NextResponse } from "next/server";

import { HTTP_STATUS, type DeviceInput, type LeaseResult } from "./licensing";
import { cleanText, clientIp, hashIp } from "./util";

export type ParsedRequest = { key: string; device: DeviceInput; ipHash: string };

/** Lee la petición de LOT Bot: { key, device: { fingerprint, name, os, app_version } }. */
export async function parseLicenseRequest(request: Request): Promise<ParsedRequest | null> {
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return null;
  }
  const device = (body.device ?? {}) as Record<string, unknown>;
  return {
    key: cleanText(body.key, 40),
    device: {
      fingerprint: cleanText(device.fingerprint ?? body.deviceId, 128),
      name: cleanText(device.name, 80),
      os: cleanText(device.os, 60),
      appVersion: cleanText(device.app_version, 30),
    },
    ipHash: hashIp(clientIp(request.headers)),
  };
}

export function invalidRequest() {
  return NextResponse.json(
    { ok: false, code: "INVALID_REQUEST", message: "Datos no válidos." },
    { status: 400, headers: { "Cache-Control": "no-store" } },
  );
}

export function leaseResponse(result: LeaseResult) {
  return NextResponse.json(result, {
    status: result.ok ? 200 : HTTP_STATUS[result.code],
    headers: { "Cache-Control": "no-store" },
  });
}
