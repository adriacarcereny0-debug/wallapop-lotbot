import { db } from "@/lib/db";
import { formatDate, formatMoney } from "@/lib/util";

export const dynamic = "force-dynamic";

type Row = {
  id: number; email: string; name: string; phone: string; created_at: Date;
  paid_cents: number; orders: number; active_license: boolean; trial: boolean;
};

export default async function CustomersPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q = "" } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<Row[]>`
    SELECT c.*,
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
      <form className="toolbar">
        <label>Buscar<input name="q" defaultValue={q} placeholder="Email, nombre o teléfono" /></label>
        <button className="btn small">Buscar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Cliente</th><th>Teléfono</th><th>Alta</th><th>Pedidos</th><th>Pagado</th><th>Licencia</th></tr></thead>
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
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="muted">No hay clientes.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
