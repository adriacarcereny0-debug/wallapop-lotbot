import { db } from "@/lib/db";
import { siteSettings } from "@/lib/store";
import { formatDate } from "@/lib/util";

import { allowTrialAgainAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = {
  id: number; email_normalized: string; created_at: Date; device_id: string | null;
  key: string | null; expires_at: Date | null; name: string | null; email: string | null; phone: string | null;
  bought: boolean;
};

export default async function TrialsPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const sql = await db();
  const rows = await sql<Row[]>`
    SELECT t.id, t.email_normalized, t.created_at, t.device_id, l.key, l.expires_at, c.name, c.email, c.phone,
      EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.status = 'pagado') AS bought
    FROM trials t
    LEFT JOIN licenses l ON l.id = t.license_id
    LEFT JOIN customers c ON c.id = l.customer_id
    ORDER BY t.id DESC LIMIT 300
  `;
  const settings = await siteSettings();
  const now = new Date();
  return (
    <>
      <h1>Pruebas gratis</h1>
      <p className="muted">
        Prueba de {settings.trial_hours} h, de un solo uso: una por email (los alias de Gmail cuentan como el mismo),
        una por ordenador y como mucho 2 por conexión cada 30 días. {settings.trial_enabled ? "" : "Ahora mismo está DESACTIVADA (Ajustes)."}
      </p>
      <Flash ok={ok} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Cliente</th><th>Clave</th><th>Pedida</th><th>Termina</th><th>¿Ha comprado?</th><th></th></tr></thead>
          <tbody>
            {rows.map((t) => {
              const live = t.expires_at && new Date(t.expires_at) > now;
              return (
                <tr key={t.id}>
                  <td>{t.name}<br /><span className="faint">{t.email ?? t.email_normalized}{t.phone ? ` · ${t.phone}` : ""}</span></td>
                  <td>{t.key ? <code>{t.key}</code> : "—"}</td>
                  <td>{formatDate(t.created_at)}</td>
                  <td><span className={`badge ${live ? "ok" : "off"}`}>{live ? formatDate(t.expires_at) : "terminada"}</span></td>
                  <td>{t.bought ? <span className="badge ok">Sí</span> : "No"}</td>
                  <td>
                    <form action={allowTrialAgainAction}>
                      <input type="hidden" name="id" value={t.id} />
                      <button className="btn small" title="Borra este registro: podrá pedir otra prueba">Permitir otra prueba</button>
                    </form>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={6} className="muted">Aún nadie ha pedido la prueba.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
