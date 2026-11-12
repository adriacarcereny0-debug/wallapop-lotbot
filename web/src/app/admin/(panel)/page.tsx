import Link from "next/link";

import { db } from "@/lib/db";
import { signingConfigured } from "@/lib/signing";
import { allPaymentMethods, plansAreExamples, siteSettings, stripeConfigured } from "@/lib/store";
import { formatDate, formatMoney } from "@/lib/util";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const sql = await db();
  const [counts] = await sql<
    {
      pending: number; paid_month: number; revenue_month: number; active: number;
      trials_week: number; trials_active: number; customers: number;
    }[]
  >`
    SELECT
      (SELECT count(*)::int FROM orders WHERE status = 'pendiente') AS pending,
      (SELECT count(*)::int FROM orders WHERE status = 'pagado' AND paid_at > date_trunc('month', now())) AS paid_month,
      (SELECT COALESCE(sum(amount_cents), 0)::int FROM orders WHERE status = 'pagado' AND paid_at > date_trunc('month', now())) AS revenue_month,
      (SELECT count(*)::int FROM licenses WHERE status = 'activa' AND kind <> 'prueba' AND (expires_at IS NULL OR expires_at > now())) AS active,
      (SELECT count(*)::int FROM trials WHERE created_at > now() - interval '7 days') AS trials_week,
      (SELECT count(*)::int FROM licenses WHERE kind = 'prueba' AND status = 'activa' AND expires_at > now()) AS trials_active,
      (SELECT count(*)::int FROM customers) AS customers
  `;
  const events = await sql<{ at: Date; actor: string; action: string; detail: string }[]>`
    SELECT at, actor, action, detail FROM events ORDER BY id DESC LIMIT 12
  `;
  const settings = await siteSettings();
  const methods = await allPaymentMethods();
  const examples = await plansAreExamples();
  const usable = methods.filter((m) => m.enabled && (m.id === "tarjeta" ? stripeConfigured() : m.instructions.trim()));
  const todo = [
    !signingConfigured() && {
      text: "Falta LICENSE_SIGNING_KEY: LOT Bot no podrá activar licencias. Genera las claves (web/scripts/generar-claves.mjs) y ponla en Vercel.",
      href: "/admin/licencias",
    },
    examples && { text: "Los planes son de EJEMPLO: pon tus precios reales.", href: "/admin/planes" },
    usable.length === 0 && { text: "No hay ninguna forma de pago lista: activa al menos una.", href: "/admin/pagos" },
    methods.some((m) => m.id === "tarjeta" && m.enabled) && !stripeConfigured() && {
      text: "Tarjeta activada pero sin claves de Stripe: no se ofrece hasta que las pongas en Vercel.",
      href: "/admin/pagos",
    },
    !settings.email && !settings.whatsapp && { text: "Añade tu email o WhatsApp de contacto.", href: "/admin/ajustes" },
    !settings.legal_name && { text: "Añade tu nombre o empresa (aparece en la web y en la privacidad).", href: "/admin/ajustes" },
  ].filter(Boolean) as { text: string; href: string }[];

  return (
    <>
      <h1>Resumen</h1>
      <p className="muted">Lo importante de un vistazo.</p>
      {todo.map((t) => (
        <div className="notice" key={t.text}>
          {t.text} <Link href={t.href}>Arreglarlo →</Link>
        </div>
      ))}
      <div className="stats">
        <Link href="/admin/pedidos?estado=pendiente" className="card stat" style={{ textDecoration: "none" }}>
          <b>{counts.pending}</b><span>Pedidos por cobrar</span>
        </Link>
        <div className="card stat"><b>{formatMoney(counts.revenue_month)}</b><span>Cobrado este mes ({counts.paid_month})</span></div>
        <div className="card stat"><b>{counts.active}</b><span>Licencias de pago activas</span></div>
        <div className="card stat"><b>{counts.trials_active}</b><span>Pruebas en curso</span></div>
        <div className="card stat"><b>{counts.trials_week}</b><span>Pruebas pedidas (7 días)</span></div>
        <div className="card stat"><b>{counts.customers}</b><span>Clientes</span></div>
      </div>
      <h2>Últimos movimientos</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fecha</th><th>Quién</th><th>Qué</th><th>Detalle</th></tr></thead>
          <tbody>
            {events.map((e, i) => (
              <tr key={i}><td>{formatDate(e.at)}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.detail}</td></tr>
            ))}
            {events.length === 0 && <tr><td colSpan={4} className="muted">Todavía no hay movimientos.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
