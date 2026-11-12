import { db } from "@/lib/db";
import { formatDate, formatMoney } from "@/lib/util";

import { passwordLinkAction, setBetaAction, setFounderAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = {
  id: number; email: string; name: string; phone: string; created_at: Date;
  paid_cents: number; orders: number; active_license: boolean; trial: boolean;
  founder: boolean; beta: boolean; has_account: boolean; subscription: string | null;
};

export default async function CustomersPage({ searchParams }: { searchParams: Promise<{ q?: string; ok?: string }> }) {
  const { q = "", ok } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<Row[]>`
    SELECT c.id, c.email, c.name, c.phone, c.created_at, c.founder, c.beta, c.password_hash IS NOT NULL AS has_account,
      (SELECT s.status FROM lotbot.subscriptions s WHERE s.customer_id = c.id ORDER BY s.id DESC LIMIT 1) AS subscription,
      COALESCE((SELECT sum(amount_cents) FROM lotbot.orders o WHERE o.customer_id = c.id AND o.status = 'pagado'), 0)::int AS paid_cents,
      (SELECT count(*)::int FROM lotbot.orders o WHERE o.customer_id = c.id) AS orders,
      EXISTS (SELECT 1 FROM lotbot.licenses l WHERE l.customer_id = c.id AND l.kind <> 'prueba' AND l.status = 'activa'
              AND (l.expires_at IS NULL OR l.expires_at > now())) AS active_license,
      EXISTS (SELECT 1 FROM lotbot.licenses l WHERE l.customer_id = c.id AND l.kind = 'prueba') AS trial
    FROM lotbot.customers c
    WHERE (${q.trim()} = '' OR lower(c.email) LIKE ${like} OR lower(c.name) LIKE ${like} OR c.phone LIKE ${like})
    ORDER BY c.id DESC LIMIT 300
  `;
  return (
    <>
      <h1>Clientes</h1>
      <p className="muted">
        «Fundador»: paga el precio de fundador del plan al suscribirse. «Enlace de contraseña»: crea un enlace de un
        solo uso (48 h) para que el cliente ponga o recupere su contraseña; envíaselo por WhatsApp o email.
      </p>
      <Flash ok={ok} />
      <form className="toolbar">
        <label>Buscar<input name="q" defaultValue={q} placeholder="Email, nombre o teléfono" /></label>
        <button className="btn small">Buscar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Cliente</th><th>Teléfono</th><th>Alta</th><th>Pedidos</th><th>Pagado</th><th>Licencia</th><th>Suscripción</th><th>Cuenta</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>{c.name || "—"}<br /><span className="faint">{c.email}</span></td>
                <td>{c.phone ? <a href={`https://wa.me/${c.phone.replace(/[^\d]/g, "")}`}>{c.phone}</a> : "—"}</td>
                <td>{formatDate(c.created_at)}</td>
                <td>{c.orders}</td>
                <td>{formatMoney(c.paid_cents)}</td>
                <td>
                  {c.active_license ? <span className="badge ok">Activa</span> : c.trial ? <span className="badge">Solo prueba</span> : <span className="badge off">No</span>}
                </td>
                <td>{c.subscription ?? "—"}</td>
                <td>
                  <div className="row-actions">
                    {c.has_account ? <span className="badge ok">Con cuenta</span> : <span className="badge off">Sin cuenta</span>}
                    <form action={setFounderAction}>
                      <input type="hidden" name="id" value={c.id} />
                      <input type="hidden" name="founder" value={c.founder ? "0" : "1"} />
                      <button className="btn small">{c.founder ? "★ Fundador (quitar)" : "Marcar fundador"}</button>
                    </form>
                    <form action={setBetaAction}>
                      <input type="hidden" name="id" value={c.id} />
                      <input type="hidden" name="beta" value={c.beta ? "0" : "1"} />
                      <button className="btn small">{c.beta ? "β Beta (quitar)" : "Beta"}</button>
                    </form>
                    <form action={passwordLinkAction}>
                      <input type="hidden" name="id" value={c.id} />
                      <button className="btn small">Enlace de contraseña</button>
                    </form>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={8} className="muted">No hay clientes.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
