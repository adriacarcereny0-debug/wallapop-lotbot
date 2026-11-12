import { headers } from "next/headers";

import { db } from "@/lib/db";
import { listPlans } from "@/lib/store";
import { formatDate, siteUrl } from "@/lib/util";

import { launchImportAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = { email: string; name: string; key: string; expires_at: Date | null; activated: boolean; has_account: boolean };

export default async function LaunchPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const sql = await db();
  const plans = await listPlans(false);
  const site = siteUrl(await headers());
  const rows = await sql<Row[]>`
    SELECT c.email, c.name, l.key, l.expires_at, c.password_hash IS NOT NULL AS has_account,
      EXISTS (SELECT 1 FROM lotbot.devices d WHERE d.license_id = l.id AND d.status = 'activo') AS activated
    FROM lotbot.licenses l JOIN lotbot.customers c ON c.id = l.customer_id
    WHERE l.notes = 'Lanzamiento (cliente fundador)'
    ORDER BY l.id DESC LIMIT 300
  `;
  const done = rows.filter((r) => r.activated).length;
  return (
    <>
      <h1>Lanzamiento</h1>
      <p className="muted">
        Pasa a tus clientes actuales a la versión con licencia. Cada uno queda como <b>fundador</b> (precio especial
        al suscribirse) y recibe una licencia gratis durante los días que elijas, para que no pare. Luego le mandas
        el mensaje de abajo por WhatsApp o email.
      </p>
      <Flash ok={ok} />
      <div className="card stack" style={{ maxWidth: 720 }}>
        <b>Plan de lanzamiento recomendado</b>
        <ol className="muted" style={{ margin: 0 }}>
          <li>Marca a 2 o 3 clientes de confianza como «Beta» (Clientes) y publica primero para ellos.</li>
          <li>Cuando les funcione una semana, da de alta aquí al resto y envíales su mensaje.</li>
          <li>Publica la versión estable (etiqueta vX.Y.Z). Al abrir LOT Bot les pedirá la clave.</li>
          <li>Cuando todos estén con el programa instalado, quítales el acceso al repositorio de GitHub.</li>
        </ol>
      </div>
      <form action={launchImportAction} className="card stack" style={{ maxWidth: 720, marginTop: 16 }}>
        <label>
          Clientes (uno por línea: <code>email, nombre</code>)
          <textarea name="clients" placeholder={"ana@ejemplo.com, Ana García\nluis@ejemplo.com, Luis"} required />
        </label>
        <div className="two">
          <label>
            Plan de la licencia
            <select name="plan" defaultValue="anual">
              {plans.map((p) => <option key={p.id} value={p.slug}>{p.name} · {p.max_devices} ordenador{p.max_devices === 1 ? "" : "es"}</option>)}
            </select>
          </label>
          <label>Días gratis<input name="days" inputMode="numeric" defaultValue={30} /></label>
        </div>
        <div><button className="btn primary">Dar de alta y crear licencias</button></div>
        <p className="faint" style={{ margin: 0 }}>Se puede repetir sin miedo: a quien ya tenga su licencia de lanzamiento no se le crea otra.</p>
      </form>

      <h2 style={{ marginTop: 28 }}>Fundadores ({done}/{rows.length} ya lo han activado)</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Cliente</th><th>Licencia</th><th>Estado</th><th>Mensaje para enviar</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const message =
                `Hola${r.name ? ` ${r.name.split(" ")[0]}` : ""}: LOT Bot ya tiene versión con licencia. ` +
                `Tu clave (gratis hasta el ${formatDate(r.expires_at).split(",")[0]}) es ${r.key}. ` +
                `1) Crea tu cuenta en ${site}/cuenta/registro con este email y la clave. ` +
                `2) Descarga LOT Bot desde Mi cuenta e instálalo (tus datos se mantienen). ` +
                `3) Al abrirlo, escribe la clave. Como cliente fundador tienes precio especial al suscribirte.`;
              return (
                <tr key={r.key}>
                  <td>{r.name || "—"}<br /><span className="faint">{r.email}</span></td>
                  <td><code>{r.key}</code><br /><span className="faint">hasta {formatDate(r.expires_at)}</span></td>
                  <td>
                    {r.activated ? <span className="badge ok">Activada</span> : <span className="badge off">Sin activar</span>}
                    <br />
                    {r.has_account ? <span className="badge ok">Con cuenta</span> : <span className="badge off">Sin cuenta</span>}
                  </td>
                  <td><textarea readOnly defaultValue={message} style={{ minHeight: 90, fontSize: 13 }} /></td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={4} className="muted">Aún no has dado de alta a ningún cliente.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
