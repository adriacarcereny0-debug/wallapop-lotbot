import type { Metadata } from "next";
import Link from "next/link";

import { billingConfigured, GRACE_DAYS, priceFor } from "@/lib/billing";
import { requireCustomer } from "@/lib/customer-auth";
import { db } from "@/lib/db";
import { listPlans } from "@/lib/store";
import { formatDate, formatMoney } from "@/lib/util";

import { logoutAction, portalAction, subscribeAction, unlinkDeviceAction } from "./actions";
import { ChangePasswordForm } from "./Forms";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Mi cuenta", robots: { index: false } };

type LicenseRow = {
  id: number; key: string; kind: string; status: string; status_reason: string;
  expires_at: Date | null; max_devices: number; plan_name: string | null;
};
type DeviceRow = {
  id: number; license_id: number; name: string; os: string; app_version: string; last_seen: Date; status: string;
};
type SubscriptionRow = {
  id: number; status: string; current_period_end: Date | null; cancel_at: Date | null;
  cancel_at_period_end: boolean; amount_cents: number | null; currency: string; plan_name: string | null;
};

const SUB_STATUS: Record<string, [string, string]> = {
  active: ["Activa", "ok"],
  trialing: ["En prueba", "ok"],
  past_due: ["Pago pendiente", "danger"],
  unpaid: ["Impagada", "danger"],
  canceled: ["Cancelada", "off"],
  incomplete: ["Pago sin completar", ""],
  incomplete_expired: ["Caducada", "off"],
  paused: ["En pausa", "off"],
};

function licenseBadge(l: LicenseRow) {
  if (l.status === "revocada") return <span className="badge danger">Revocada</span>;
  if (l.status === "suspendida") return <span className="badge danger">Suspendida{l.status_reason ? ` · ${l.status_reason}` : ""}</span>;
  if (l.expires_at && new Date(l.expires_at) <= new Date()) return <span className="badge off">Caducada</span>;
  return <span className="badge ok">Activa</span>;
}

export default async function AccountPage({ searchParams }: { searchParams: Promise<{ ok?: string; error?: string; pago?: string }> }) {
  const customer = await requireCustomer();
  const { ok, error, pago } = await searchParams;
  const sql = await db();
  const licenses = await sql<LicenseRow[]>`
    SELECT l.id, l.key, l.kind, l.status, l.status_reason, l.expires_at, l.max_devices, p.name AS plan_name
    FROM lotbot.licenses l LEFT JOIN lotbot.plans p ON p.id = l.plan_id
    WHERE l.customer_id = ${customer.id} ORDER BY l.id DESC
  `;
  const devices = await sql<DeviceRow[]>`
    SELECT d.id, d.license_id, d.name, d.os, d.app_version, d.last_seen, d.status FROM lotbot.devices d
    JOIN lotbot.licenses l ON l.id = d.license_id
    WHERE l.customer_id = ${customer.id} AND d.status <> 'desvinculado' ORDER BY d.last_seen DESC
  `;
  const subscriptions = await sql<SubscriptionRow[]>`
    SELECT s.id, s.status, s.current_period_end, s.cancel_at, s.cancel_at_period_end, s.amount_cents, s.currency, p.name AS plan_name
    FROM lotbot.subscriptions s LEFT JOIN lotbot.plans p ON p.id = s.plan_id
    WHERE s.customer_id = ${customer.id} ORDER BY s.id DESC
  `;
  const live = subscriptions.find((s) => ["active", "trialing", "past_due", "unpaid", "incomplete"].includes(s.status));
  const plans = (await listPlans()).filter((p) => p.billing_interval);
  const billing = billingConfigured();

  return (
    <div className="form-page">
      <div className="wrap" style={{ maxWidth: 880 }}>
        <div style={{ display: "flex", alignItems: "end", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div className="eyebrow">Mi cuenta</div>
            <h1 className="title" style={{ fontSize: 34, letterSpacing: "-0.03em", margin: "6px 0 0" }}>
              Hola{customer.name ? `, ${customer.name.split(" ")[0]}` : ""}
            </h1>
            <p className="faint" style={{ margin: "4px 0 0" }}>{customer.email}{customer.founder ? " · Cliente fundador" : ""}</p>
          </div>
          <form action={logoutAction} style={{ marginLeft: "auto" }}>
            <button className="btn small">Salir</button>
          </form>
        </div>

        {ok && <div className="notice ok">{ok}</div>}
        {error && <div className="notice">{error}</div>}
        {pago === "cancelado" && <div className="notice">Has salido del pago sin terminarlo. No se ha cobrado nada.</div>}

        {/* Suscripción */}
        <section className="card stack" style={{ marginTop: 22, padding: 24 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>Suscripción</h2>
          {live ? (
            <>
              <p style={{ margin: 0 }}>
                <b>{live.plan_name ?? "LOT Bot"}</b>{" "}
                {live.amount_cents != null && <>· {formatMoney(live.amount_cents, live.currency)}</>}{" "}
                <span className={`badge ${SUB_STATUS[live.status]?.[1] ?? ""}`}>{SUB_STATUS[live.status]?.[0] ?? live.status}</span>
              </p>
              <p className="muted" style={{ margin: 0 }}>
                {live.cancel_at_period_end || live.cancel_at
                  ? `Cancelada: funciona hasta el ${formatDate(live.cancel_at ?? live.current_period_end)} y no se vuelve a cobrar.`
                  : live.status === "past_due"
                    ? `No se ha podido cobrar. Actualiza la tarjeta: LOT Bot sigue funcionando ${GRACE_DAYS} días de margen desde el ${formatDate(live.current_period_end)}.`
                    : `Próxima renovación: ${formatDate(live.current_period_end)}.`}
              </p>
              {billing && (
                <form action={portalAction}>
                  <button className="btn small">Pago y facturas (cambiar tarjeta, plan o cancelar)</button>
                </form>
              )}
            </>
          ) : !billing ? (
            <p className="muted" style={{ margin: 0 }}>
              El pago con tarjeta aún no está disponible. Mientras tanto, <Link href="/#precios">mira los planes</Link> o escríbenos.
            </p>
          ) : (
            <>
              <p className="muted" style={{ margin: 0 }}>
                No tienes ninguna suscripción activa. Elige un plan: se renueva solo y lo cancelas cuando quieras.
                {licenses.length > 0 && " Tu clave de licencia de siempre seguirá valiendo."}
              </p>
              <div className="plans">
                {plans.map((plan) => {
                  const price = priceFor(plan, customer.founder);
                  return (
                    <form key={plan.id} action={subscribeAction} className={`card plan${plan.highlighted ? " featured" : ""}`}>
                      <input type="hidden" name="plan" value={plan.slug} />
                      <b>{plan.name}</b>
                      <div className="price">
                        {formatMoney(price, plan.currency)} <small>/ {plan.period_label}</small>
                      </div>
                      {price !== plan.price_cents && (
                        <span className="faint">Precio de fundador (normal: {formatMoney(plan.price_cents, plan.currency)})</span>
                      )}
                      <span className="faint">Hasta {plan.max_devices} ordenador{plan.max_devices === 1 ? "" : "es"}</span>
                      <button className="btn primary">Suscribirme</button>
                    </form>
                  );
                })}
              </div>
            </>
          )}
          {subscriptions.length > (live ? 1 : 0) && (
            <details>
              <summary className="faint" style={{ cursor: "pointer" }}>Suscripciones anteriores</summary>
              <ul className="faint">
                {subscriptions.filter((s) => s !== live).map((s) => (
                  <li key={s.id}>{s.plan_name ?? "LOT Bot"} · {SUB_STATUS[s.status]?.[0] ?? s.status} · {formatDate(s.current_period_end)}</li>
                ))}
              </ul>
            </details>
          )}
        </section>

        {/* Licencias */}
        <section className="card stack" style={{ marginTop: 18, padding: 24 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>Tu licencia</h2>
          {licenses.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              Todavía no tienes licencia. Suscríbete arriba o <Link href="/prueba">pide la prueba gratis de 24 h</Link>.
            </p>
          ) : (
            licenses.map((l) => (
              <div key={l.id} className="stack" style={{ gap: 8 }}>
                <div className="keybox" style={{ fontSize: 20 }}>{l.key}</div>
                <p style={{ margin: 0 }}>
                  {licenseBadge(l)}{" "}
                  <span className="muted">
                    {l.kind === "prueba" ? "Prueba gratis" : l.plan_name ?? "Licencia"} · hasta {l.max_devices} ordenador
                    {l.max_devices === 1 ? "" : "es"} · {l.expires_at ? `vale hasta el ${formatDate(l.expires_at)}` : "sin caducidad"}
                  </span>
                </p>
              </div>
            ))
          )}
          <p className="faint" style={{ margin: 0 }}>
            Escribe la clave en LOT Bot (Configuración → Licencia). LOT Bot la comprueba solo cada pocas horas y
            funciona hasta 3 días sin Internet.
          </p>
        </section>

        {/* Ordenadores */}
        <section className="card stack" style={{ marginTop: 18, padding: 24 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>Tus ordenadores</h2>
          {devices.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>Aún no has activado LOT Bot en ningún ordenador.</p>
          ) : (
            <div className="table-wrap" style={{ margin: 0 }}>
              <table>
                <thead><tr><th>Ordenador</th><th>Versión</th><th>Último uso</th><th></th></tr></thead>
                <tbody>
                  {devices.map((d) => (
                    <tr key={d.id}>
                      <td>{d.name || "Ordenador"}<br /><span className="faint">{d.os}</span></td>
                      <td>{d.app_version || "—"}</td>
                      <td>{formatDate(d.last_seen)}</td>
                      <td>
                        {d.status === "bloqueado" ? (
                          <span className="badge danger">Bloqueado</span>
                        ) : (
                          <form action={unlinkDeviceAction}>
                            <input type="hidden" name="device" value={d.id} />
                            <button className="btn small">Desvincular</button>
                          </form>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="faint" style={{ margin: 0 }}>
            Para usar LOT Bot en otro ordenador, desvincula uno (hasta 3 veces al mes) y activa la licencia en el nuevo.
          </p>
        </section>

        {/* Seguridad */}
        <section className="card" style={{ marginTop: 18, padding: 24 }}>
          <details>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Cambiar contraseña</summary>
            <div style={{ marginTop: 14, maxWidth: 420 }}><ChangePasswordForm /></div>
          </details>
        </section>
      </div>
    </div>
  );
}
