// Genera la pareja de claves para firmar las licencias (Ed25519).
//   node scripts/generar-claves.mjs
// · LICENSE_SIGNING_KEY → en Vercel (Settings → Environment Variables). SECRETA.
// · Clave pública → la lleva LOT Bot dentro (no es secreta).
import { createHash, generateKeyPairSync } from "node:crypto";

const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const raw = publicKey.export({ format: "der", type: "spki" }).subarray(-32);
console.log("\nLICENSE_SIGNING_KEY (SECRETA, solo en Vercel):\n");
console.log(privateKey.export({ format: "der", type: "pkcs8" }).toString("base64"));
console.log("\nClave PÚBLICA (para LOT Bot):\n");
console.log(raw.toString("base64"));
console.log(`\nIdentificador: ${createHash("sha256").update(raw).digest("hex").slice(0, 8)}\n`);
console.log("Guarda la clave secreta en un gestor de contraseñas: si se pierde, hay que");
console.log("publicar una versión de LOT Bot con la clave nueva.\n");
