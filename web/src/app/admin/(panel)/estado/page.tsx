import { billingConfigured } from "@/lib/billing";
import { accountsConfigured } from "@/lib/customer-auth";
import { db, SCHEMA_VERSION } from "@/lib/db";
import { currentKeyId, signingConfigured } from "@/lib/signing";
import { twoFactorEnabled } from "@/lib/totp";
import { formatDate } from "@/lib/util";

export const dynamic = "force-dynamic";

/** Identificador de la clave pública que lleva LOT Bot dentro. */
const APP_KEY_ID = "f9607729";

type Check = { name: string; ok: boolean | null; detail: string; fix?: string };

export default async function StatusPage() {
  const sql = await db();
  const [schema] = await sql<{ version: number }[]>`SELECT max(version)::int AS version FROM lotbot.schema_migrations`;
  const [last] = await sql<{ webhook: Date | null; release: Date | null; refresh: Date | null }[]>`
    SELECT
      (SELECT max(received_at) FROM lotbot.stripe_events) AS webhook,
      (SELECT max(created_at) FROM lotbot.releases WHERE status = 'activa') AS release,
      (SELECT max(last_seen) FROM lotbot.devices) AS refresh
  `;
  const kid = currentKeyId();
  const checks: Check[] = [
    { name: "Base de datos", ok: true, detail: `conectada · esquema ${schema.version} (esta web espera el ${SCHEMA_VERSION})` },
    {
      name: "Firma de licencias",
      ok: signingConfigured() && kid === APP_KEY_ID,
      detail: signingConfigured() ? `clave ${kid}${kid === APP_KEY_ID ? " (la que lleva LOT Bot)" : ` — LOT Bot espera ${APP_KEY_ID}`}` : "falta",
      fix: "LICENSE_SIGNING_KEY en Vercel. No la cambies: LOT Bot solo acepta la f9607729.",
    },
    { name: "SESSION_SECRET", ok: Boolean(process.env.SESSION_SECRET), detail: process.env.SESSION_SECRET ? "puesto" : "falta (se usa ADMIN_PASSWORD en su lugar)", fix: "Texto largo y aleatorio en Vercel." },
    { name: "SITE_URL", ok: Boolean(process.env.SITE_URL), detail: process.env.SITE_URL || "falta", fix: "https://www.lotbot.es" },
    { name: "Verificación en dos pasos (/admin)", ok: await twoFactorEnabled(), detail: (await twoFactorEnabled()) ? "activada" : "desactivada", fix: "Admin → Seguridad." },
    { name: "Cuentas de cliente", ok: accountsConfigured(), detail: accountsConfigured() ? "disponibles" : "no disponibles" },
    {
      name: "Stripe (suscripciones)",
      ok: billingConfigured(),
      detail: billingConfigured() ? `configurado · último aviso recibido: ${formatDate(last.webhook)}` : "sin configurar",
      fix: "STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET (ver web/README.md).",
    },
    {
      name: "Registro de versiones (GitHub)",
      ok: (process.env.RELEASE_API_TOKEN ?? "").length >= 24,
      detail: (process.env.RELEASE_API_TOKEN ?? "").length >= 24 ? `listo · última versión: ${formatDate(last.release)}` : "falta RELEASE_API_TOKEN",
      fix: "El mismo token en Vercel y en GitHub → Secrets.",
    },
    {
      name: "Descargas desde GitHub privado",
      ok: Boolean(process.env.GITHUB_RELEASES_REPO && process.env.GITHUB_RELEASES_TOKEN),
      detail: process.env.GITHUB_RELEASES_REPO ? process.env.GITHUB_RELEASES_REPO : "sin configurar",
      fix: "GITHUB_RELEASES_REPO y GITHUB_RELEASES_TOKEN (solo lectura).",
    },
    { name: "Última comprobación de licencia recibida", ok: null, detail: formatDate(last.refresh) },
  ];
  return (
    <>
      <h1>Estado del sistema</h1>
      <p className="muted">
        Qué está configurado y qué falta. Los errores de la web se ven en Vercel → Logs; la vigilancia de cada hora y
        las copias de seguridad, en GitHub → Actions.
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Qué</th><th>Estado</th><th>Detalle</th><th>Cómo arreglarlo</th></tr></thead>
          <tbody>
            {checks.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{c.ok === null ? <span className="badge off">info</span> : c.ok ? <span className="badge ok">bien</span> : <span className="badge danger">revisar</span>}</td>
                <td>{c.detail}</td>
                <td className="faint">{c.ok ? "" : c.fix ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
