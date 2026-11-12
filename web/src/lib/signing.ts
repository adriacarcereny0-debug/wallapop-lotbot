/**
 * Firma de los «pases» de licencia (Ed25519).
 *
 * La clave PRIVADA solo existe en el servidor (variable LICENSE_SIGNING_KEY).
 * LOT Bot lleva dentro la clave PÚBLICA: con ella comprueba que un pase lo
 * ha emitido este servidor y que nadie lo ha cambiado. Sin la privada no se
 * puede fabricar un pase válido.
 *
 * Formato del pase:  LBT1.<datos en base64url>.<firma en base64url>
 * (se firma el texto «LBT1.<datos>»).
 */
import { createHash, createPrivateKey, createPublicKey, generateKeyPairSync, sign, type KeyObject } from "node:crypto";

export const TOKEN_PREFIX = "LBT1";

export type LeasePayload = {
  v: 1;
  typ: "lotbot-lease";
  kid: string;
  lic: number;
  kh: string;
  dev: string;
  kind: string;
  plan: string | null;
  seats: number;
  lic_exp: number | null;
  iat: number;
  exp: number;
};

let cached: { key: KeyObject; publicRaw: Buffer; kid: string } | null = null;

function b64url(data: Buffer): string {
  return data.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function loadKey() {
  if (cached) return cached;
  const raw = process.env.LICENSE_SIGNING_KEY?.trim();
  if (!raw) return null;
  const key = createPrivateKey({ key: Buffer.from(raw, "base64"), format: "der", type: "pkcs8" });
  if (key.asymmetricKeyType !== "ed25519") throw new Error("LICENSE_SIGNING_KEY no es una clave Ed25519.");
  const publicRaw = publicKeyRaw(createPublicKey(key));
  cached = { key, publicRaw, kid: keyId(publicRaw) };
  return cached;
}

function publicKeyRaw(publicKey: KeyObject): Buffer {
  // SPKI de Ed25519 = 12 bytes de cabecera + 32 bytes de clave.
  return (publicKey.export({ format: "der", type: "spki" }) as Buffer).subarray(-32);
}

/** Identificador corto de la clave (para poder cambiarla algún día). */
export function keyId(publicRaw: Buffer): string {
  return createHash("sha256").update(publicRaw).digest("hex").slice(0, 8);
}

export function signingConfigured(): boolean {
  try {
    return loadKey() !== null;
  } catch {
    return false;
  }
}

/** Clave pública en base64 (32 bytes): la que se pone dentro de LOT Bot. */
export function publicKeyBase64(): string | null {
  const loaded = loadKey();
  return loaded ? loaded.publicRaw.toString("base64") : null;
}

export function currentKeyId(): string | null {
  return loadKey()?.kid ?? null;
}

export function signLease(payload: Omit<LeasePayload, "kid" | "v" | "typ">): string {
  const loaded = loadKey();
  if (!loaded) throw new Error("Falta LICENSE_SIGNING_KEY.");
  const full: LeasePayload = { v: 1, typ: "lotbot-lease", kid: loaded.kid, ...payload };
  const body = `${TOKEN_PREFIX}.${b64url(Buffer.from(JSON.stringify(full), "utf8"))}`;
  const signature = sign(null, Buffer.from(body, "utf8"), loaded.key);
  return `${body}.${b64url(signature)}`;
}

/** Datos de una actualización: versión, plataforma y huella SHA-256 del instalador. */
export type UpdatePayload = {
  v: 1;
  typ: "lotbot-update";
  kid: string;
  ver: string;
  plat: string;
  sha256: string;
  size: number;
  mandatory: boolean;
  dev: string;
  iat: number;
  exp: number;
};

/** Firma lo que LOT Bot tiene que comprobar antes de instalar una versión. */
export function signUpdate(payload: Omit<UpdatePayload, "kid" | "v" | "typ">): string {
  const loaded = loadKey();
  if (!loaded) throw new Error("Falta LICENSE_SIGNING_KEY.");
  const full: UpdatePayload = { v: 1, typ: "lotbot-update", kid: loaded.kid, ...payload };
  const body = `${TOKEN_PREFIX}.${b64url(Buffer.from(JSON.stringify(full), "utf8"))}`;
  return `${body}.${b64url(sign(null, Buffer.from(body, "utf8"), loaded.key))}`;
}

/** Lista firmada de huellas de los ficheros oficiales de una versión. */
export function signIntegrity(payload: { ver: string; plat: string; files: Record<string, string>; dev: string; iat: number; exp: number }): string {
  const loaded = loadKey();
  if (!loaded) throw new Error("Falta LICENSE_SIGNING_KEY.");
  const full = { v: 1, typ: "lotbot-integrity", kid: loaded.kid, ...payload };
  const body = `${TOKEN_PREFIX}.${b64url(Buffer.from(JSON.stringify(full), "utf8"))}`;
  return `${body}.${b64url(sign(null, Buffer.from(body, "utf8"), loaded.key))}`;
}

/** Huella de la clave de licencia (el pase no lleva la clave en claro). */
export function keyHash(licenseKey: string): string {
  return createHash("sha256").update(licenseKey.trim().toUpperCase()).digest("hex").slice(0, 16);
}

/** Para el script de claves y las pruebas. */
export function generateSigningKey(): { privateKey: string; publicKey: string; kid: string } {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const raw = publicKeyRaw(publicKey);
  return {
    privateKey: (privateKey.export({ format: "der", type: "pkcs8" }) as Buffer).toString("base64"),
    publicKey: raw.toString("base64"),
    kid: keyId(raw),
  };
}
