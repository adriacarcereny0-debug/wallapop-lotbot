import { db } from "@/lib/db";
import { formatDate, formatMoney } from "@/lib/util";

import { cancelOrderAction, markPaidAction, orderNotesAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = {
  id: number; reference: string; plan_name: string; method: string; amount_cents: number; currency: string;
  status: string; created_at: Date; paid_at: Date | null; notes: string; email: string | null;
  name: string | null; phone: string | null; license_key: string | null;
};

export default async function OrdersPage({ searchParams }: { searchParams: Promise<{ estado?: string; q?: string; ok?: string }> }) {
  const { estado = "", q = "", ok } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<Row[]>`
    SELECT o.*, c.email, c.name, c.phone, l.key AS license_key
    FROM lotbot.orders o
    LEFT JOIN lotbot.customers c ON c.id = o.customer_id
    LEFT JOIN lotbot.licenses l ON l.id = o.license_id
    WHERE (${estado} = '' OR o.status = ${estado})
      AND (${q.trim()} = '' OR lower(o.reference) LIKE ${like} OR lower(c.email) LIKE ${like} OR lower(c.name) LIKE ${like})
    ORDER BY o.id DESC LIMIT 200
  `;
  return (
    <>
      <h1>Pedidos</h1>
      <p className="muted">
        Bizum, transferencia y PayPal se confirman a mano: cuando veas el dinero, pulsa «Marcar pagado» y se crea la
        licencia (el cliente la ve en la página de su pedido). Los de tarjeta se confirman solos.
      </p>
      <Flash ok={ok} />
      <form className="toolbar">
        <label>Estado
          <select name="estado" defaultValue={estado}>
            <option value="">Todos</option>
            <option value="pendiente">Pendientes</option>
            <option value="pagado">Pagados</option>
            <option value="cancelado">Cancelados</option>
          </select>
        </label>
        <label>Buscar<input name="q" defaultValue={q} placeholder="Referencia, email o nombre" /></label>
        <button className="btn small">Filtrar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Referencia</th><th>Cliente</th><th>Plan</th><th>Pago</th><th>Importe</th><th>Estado</th><th>Fecha</th><th>Licencia</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.id}>
                <td><code>{o.reference}</code></td>
                <td>{o.name}<br /><span className="faint">{o.email}{o.phone ? ` · ${o.phone}` : ""}</span></td>
                <td>{o.plan_name}</td>
                <td>{o.method}</td>
                <td>{formatMoney(o.amount_cents, o.currency)}</td>
                <td>
                  <span className={`badge ${o.status === "pagado" ? "ok" : o.status === "cancelado" ? "off" : ""}`}>{o.status}</span>
                </td>
                <td>{formatDate(o.created_at)}{o.paid_at && <><br /><span className="faint">pagado {formatDate(o.paid_at)}</span></>}</td>
                <td>{o.license_key ? <code>{o.license_key}</code> : "—"}</td>
                <td>
                  <div className="row-actions">
                    {o.status === "pendiente" && (
                      <>
                        <form action={markPaidAction}><input type="hidden" name="id" value={o.id} /><button className="btn small primary">Marcar pagado</button></form>
                        <form action={cancelOrderAction}><input type="hidden" name="id" value={o.id} /><button className="btn small danger">Cancelar</button></form>
                      </>
                    )}
                    <form action={orderNotesAction} style={{ display: "flex", gap: 6 }}>
                      <input type="hidden" name="id" value={o.id} />
                      <input name="notes" defaultValue={o.notes} placeholder="Nota" style={{ padding: "6px 8px", minWidth: 120 }} />
                      <button className="btn small">Guardar</button>
                    </form>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={9} className="muted">No hay pedidos.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
