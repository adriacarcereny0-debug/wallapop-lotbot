import Link from "next/link";

import { licenseAlerts } from "@/lib/alerts";
import { db } from "@/lib/db";
import { signingConfigured } from "@/lib/signing";
import { twoFactorEnabled } from "@/lib/totp";
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
      (SELECT count(*)::int FROM lotbot.orders WHERE status = 'pendiente') AS pending,
      (SELECT count(*)::int FROM lotbot.orders WHERE status = 'pagado' AND paid_at > date_trunc('month', now())) AS paid_month,
      (SELECT COALESCE(sum(amount_cents), 0)::int FROM lotbot.orders WHERE status = 'pagado' AND paid_at > date_trunc('month', now())) AS revenue_month,
      (SELECT count(*)::int FROM lotbot.licenses WHERE status = 'activa' AND kind <> 'prueba' AND (expires_at IS NULL OR expires_at > now())) AS active,
      (SELECT count(*)::int FROM lotbot.trials WHERE created_at > now() - interval '7 days') AS trials_week,
      (SELECT count(*)::int FROM lotbot.licenses WHERE kind = 'prueba' AND status = 'activa' AND expires_at > now()) AS trials_active,
      (SELECT count(*)::int FROM lotbot.customers) AS customers
  `;
  const events = await sql<{ at: Date; actor: string; action: string; detail: string }[]>`
    SELECT at, actor, action, detail FROM lotbot.events ORDER BY id DESC LIMIT 12
  `;
  const settings = await siteSettings();
  const methods = await allPaymentMethods();
  const examples = await plansAreExamples();
  const usable = methods.filter((m) => m.enabled && (m.id === "tarjeta" ? stripeConfigured() : m.instructions.trim()));
  const alerts = await licenseAlerts();
  // Negocio (suscripciones de Stripe y pruebas gratis).
  const [biz] = await sql<{
    mrr_cents: number; subs_active: number; past_due: number; new_30: number; churn_30: number;
    trials_30: number; trials_converted: number;
  }[]>`
    SELECT
      COALESCE(sum(CASE WHEN p.billing_interval = 'year' THEN s.amount_cents / 12.0 ELSE s.amount_cents END)
        FILTER (WHERE s.status IN ('active', 'past_due') AND NOT s.cancel_at_period_end AND s.cancel_at IS NULL), 0)::int AS mrr_cents,
      count(*) FILTER (WHERE s.status IN ('active', 'trialing'))::int AS subs_active,
      count(*) FILTER (WHERE s.status IN ('past_due', 'unpaid'))::int AS past_due,
      count(*) FILTER (WHERE s.created_at > now() - interval '30 days')::int AS new_30,
      count(*) FILTER (WHERE s.status = 'canceled' AND s.ended_at > now() - interval '30 days')::int AS churn_30,
      (SELECT count(*)::int FROM lotbot.trials t WHERE t.created_at > now() - interval '30 days') AS trials_30,
      (SELECT count(*)::int FROM lotbot.trials t JOIN lotbot.licenses l ON l.id = t.license_id
        WHERE t.created_at > now() - interval '30 days' AND l.kind = 'pago') AS trials_converted
    FROM lotbot.subscriptions s LEFT JOIN lotbot.plans p ON p.id = s.plan_id
  `;
  const conversion = biz.trials_30 ? Math.round((biz.trials_converted / biz.trials_30) * 100) : null;
  const todo = [
    alerts.length > 0 && {
      text: `Hay ${alerts.length} alerta${alerts.length === 1 ? "" : "s"} de posible abuso de licencias.`,
      href: "/admin/alertas",
    },
    !(await twoFactorEnabled()) && {
      text: "Activa la verificación en dos pasos para entrar en /admin.",
      href: "/admin/seguridad",
    },
    !process.env.SESSION_SECRET && {
      text: "Falta SESSION_SECRET en Vercel: pon un texto largo y aleatorio (protege la sesión de /admin).",
      href: "/admin",
    },
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
      <h2>Negocio</h2>
      <div className="stats">
        <div className="card stat"><b>{formatMoney(biz.mrr_cents)}</b><span>Ingresos recurrentes al mes</span></div>
        <Link href="/admin/suscripciones" className="card stat" style={{ textDecoration: "none" }}>
          <b>{biz.subs_active}</b><span>Suscripciones activas</span>
        </Link>
        <Link href="/admin/suscripciones?estado=past_due" className="card stat" style={{ textDecoration: "none" }}>
          <b>{biz.past_due}</b><span>Con pago fallido</span>
        </Link>
        <div className="card stat"><b>+{biz.new_30} / −{biz.churn_30}</b><span>Altas / bajas (30 días)</span></div>
        <div className="card stat">
          <b>{conversion == null ? "—" : `${conversion} %`}</b>
          <span>Pruebas que pasan a pago (30 días: {biz.trials_converted}/{biz.trials_30})</span>
        </div>
      </div>
      <h2>Ventas y licencias</h2>
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
