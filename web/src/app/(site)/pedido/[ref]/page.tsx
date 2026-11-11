import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { db } from "@/lib/db";
import { getOrder, siteSettings } from "@/lib/store";
import { formatDate, formatMoney } from "@/lib/util";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Tu pedido", robots: { index: false } };

export default async function OrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ ref: string }>;
  searchParams: Promise<{ pago?: string }>;
}) {
  const { ref } = await params;
  const { pago } = await searchParams;
  if (!/^LOT-[A-Z0-9]{8}$/.test(ref)) notFound();
  const order = await getOrder(ref);
  if (!order) notFound();
  const sql = await db();
  const [method] = await sql<{ name: string; instructions: string }[]>`
    SELECT name, instructions FROM payment_methods WHERE id = ${order.method}
  `;
  const settings = await siteSettings();
  const whatsapp = settings.whatsapp.replace(/[^\d]/g, "");
  const amount = formatMoney(order.amount_cents, order.currency);
  const instructions = (method?.instructions || "")
    .replaceAll("{referencia}", order.reference)
    .replaceAll("{importe}", amount);

  return (
    <div className="form-page">
      <div className="wrap panel stack">
        <div className="eyebrow">Pedido {order.reference}</div>
        <h1 className="title" style={{ fontSize: 34, letterSpacing: "-0.03em", margin: 0 }}>
          {order.status === "pagado" ? "¡Pago recibido!" : order.status === "cancelado" ? "Pedido cancelado" : "Pedido pendiente de pago"}
        </h1>
        <div className="card stack">
          <div>
            <b>{order.plan_name}</b> · {amount} · {method?.name ?? order.method}
            <div className="faint">Creado el {formatDate(order.created_at)}</div>
          </div>
          {order.status === "pagado" && order.license_key && (
            <>
              <p className="muted" style={{ margin: 0 }}>Esta es tu clave de licencia:</p>
              <div className="keybox">{order.license_key}</div>
              <p className="faint" style={{ margin: 0 }}>
                {order.license_expires ? `Válida hasta el ${formatDate(order.license_expires)}.` : "Sin caducidad."}
              </p>
            </>
          )}
          {order.status === "pendiente" && order.method === "tarjeta" && (
            <p className="muted" style={{ margin: 0 }}>
              {pago === "cancelado"
                ? "Has cancelado el pago con tarjeta. Puedes volver a intentarlo desde la página de precios."
                : "Estamos esperando la confirmación de Stripe. Recarga esta página en unos segundos."}
            </p>
          )}
          {order.status === "pendiente" && order.method !== "tarjeta" && (
            <>
              <p className="muted" style={{ margin: 0 }}>
                Para completar la compra, paga <b>{amount}</b> así e indica la referencia <b>{order.reference}</b>:
              </p>
              <div className="prose card" style={{ background: "var(--bg-2)" }}>{instructions || "Escríbenos y te damos los datos de pago."}</div>
              <p className="faint" style={{ margin: 0 }}>
                En cuanto lo recibamos activamos tu licencia y la verás en esta misma página (guárdala en favoritos).
              </p>
            </>
          )}
        </div>
        <div className="toolbar">
          {whatsapp && (
            <a className="btn" href={`https://wa.me/${whatsapp}?text=${encodeURIComponent(`Hola, mi pedido de LOT Bot es ${order.reference}`)}`}>
              Escribir por WhatsApp
            </a>
          )}
          <Link className="btn" href="/">Volver al inicio</Link>
        </div>
      </div>
    </div>
  );
}
