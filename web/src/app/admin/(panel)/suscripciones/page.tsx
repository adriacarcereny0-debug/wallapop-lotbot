import { billingConfigured, GRACE_DAYS } from "@/lib/billing";
import { db } from "@/lib/db";
import { formatDate, formatMoney } from "@/lib/util";

export const dynamic = "force-dynamic";

type Row = {
  id: number; stripe_subscription_id: string; status: string; current_period_end: Date | null;
  cancel_at_period_end: boolean; cancel_at: Date | null; amount_cents: number | null; currency: string;
  email: string | null; plan_name: string | null; license_key: string | null; license_expires: Date | null;
  updated_at: Date;
};

const LABELS: Record<string, [string, string]> = {
  active: ["Activa", "ok"], trialing: ["En prueba", "ok"], past_due: ["Pago fallido", "danger"],
  unpaid: ["Impagada", "danger"], canceled: ["Cancelada", "off"], incomplete: ["Sin completar", ""],
  incomplete_expired: ["Caducada", "off"], paused: ["En pausa", "off"],
};

export default async function SubscriptionsPage({ searchParams }: { searchParams: Promise<{ estado?: string }> }) {
  const { estado = "" } = await searchParams;
  const sql = await db();
  const rows = await sql<Row[]>`
    SELECT s.*, c.email, p.name AS plan_name, l.key AS license_key, l.expires_at AS license_expires
    FROM lotbot.subscriptions s
    LEFT JOIN lotbot.customers c ON c.id = s.customer_id
    LEFT JOIN lotbot.plans p ON p.id = s.plan_id
    LEFT JOIN lotbot.licenses l ON l.id = s.license_id
    WHERE (${estado} = '' OR s.status = ${estado})
    ORDER BY s.updated_at DESC LIMIT 500
  `;
  const [totals] = await sql<{ active: number; past_due: number; mrr_cents: number }[]>`
    SELECT
      count(*) FILTER (WHERE status IN ('active', 'trialing'))::int AS active,
      count(*) FILTER (WHERE status IN ('past_due', 'unpaid'))::int AS past_due,
      COALESCE(sum(CASE WHEN p.billing_interval = 'year' THEN s.amount_cents / 12.0 ELSE s.amount_cents END)
        FILTER (WHERE s.status IN ('active', 'past_due') AND NOT s.cancel_at_period_end), 0)::int AS mrr_cents
    FROM lotbot.subscriptions s LEFT JOIN lotbot.plans p ON p.id = s.plan_id
  `;
  return (
    <>
      <h1>Suscripciones</h1>
      <p className="muted">
        Las crea y actualiza Stripe solo (pagos, renovaciones, impagos y cancelaciones). La licencia vale hasta el
        fin del periodo pagado + {GRACE_DAYS} días de margen por si falla un cobro; si se cancela, hasta el fin del
        periodo. Una suspensión o revocación hecha a mano en «Licencias» no la deshace Stripe.
      </p>
      {!billingConfigured() && (
        <div className="notice">Falta configurar Stripe (STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET en Vercel).</div>
      )}
      <div className="stats">
        <div className="card stat"><b>{totals.active}</b><span>Activas</span></div>
        <div className="card stat"><b>{totals.past_due}</b><span>Con pago fallido</span></div>
        <div className="card stat"><b>{formatMoney(totals.mrr_cents)}</b><span>Ingresos al mes (aprox.)</span></div>
      </div>
      <form className="toolbar">
        <label>
          Estado
          <select name="estado" defaultValue={estado}>
            <option value="">Todas</option>
            {Object.entries(LABELS).map(([value, [label]]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button className="btn small">Filtrar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Cliente</th><th>Plan</th><th>Estado</th><th>Periodo hasta</th><th>Licencia</th><th>Stripe</th></tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>{s.email ?? "—"}</td>
                <td>{s.plan_name ?? "—"}<br /><span className="faint">{s.amount_cents != null ? formatMoney(s.amount_cents, s.currency) : ""}</span></td>
                <td>
                  <span className={`badge ${LABELS[s.status]?.[1] ?? ""}`}>{LABELS[s.status]?.[0] ?? s.status}</span>
                  {(s.cancel_at_period_end || s.cancel_at) && <><br /><span className="faint">Se cancela al final</span></>}
                </td>
                <td>{formatDate(s.current_period_end)}</td>
                <td>{s.license_key ? <><code>{s.license_key}</code><br /><span className="faint">hasta {formatDate(s.license_expires)}</span></> : "—"}</td>
                <td>
                  <a href={`https://dashboard.stripe.com/subscriptions/${s.stripe_subscription_id}`} target="_blank" rel="noreferrer">
                    Ver ↗
                  </a>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="muted">Aún no hay suscripciones.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
