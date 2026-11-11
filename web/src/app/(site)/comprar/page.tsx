import type { Metadata } from "next";
import Link from "next/link";

import { hasDatabase } from "@/lib/db";
import { getPlan, listPlans, publicPaymentMethods } from "@/lib/store";
import { formatMoney } from "@/lib/util";

import CheckoutForm from "./CheckoutForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Comprar" };

export default async function BuyPage({ searchParams }: { searchParams: Promise<{ plan?: string }> }) {
  const { plan: slug } = await searchParams;
  if (!hasDatabase()) {
    return <div className="form-page"><div className="wrap panel card">La tienda aún no está configurada.</div></div>;
  }
  const plans = await listPlans();
  const plan = (slug && (await getPlan(slug))) || plans.find((p) => p.highlighted) || plans[0];
  const methods = await publicPaymentMethods();
  if (!plan) {
    return <div className="form-page"><div className="wrap panel card">No hay planes disponibles ahora mismo.</div></div>;
  }
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Comprar</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0" }}>
          LOT Bot · {plan.name}
        </h1>
        <p className="muted">
          {formatMoney(plan.price_cents, plan.currency)} / {plan.period_label}
          {plan.duration_days ? ` · ${plan.duration_days} días de licencia` : " · licencia sin caducidad"}
          {` · ${plan.max_devices} ordenador${plan.max_devices === 1 ? "" : "es"}`}.{" "}
          <Link href="/#precios">Cambiar de plan</Link>
        </p>
        {methods.length ? (
          <CheckoutForm
            plans={plans.map((p) => ({ slug: p.slug, label: `${p.name} · ${formatMoney(p.price_cents, p.currency)} / ${p.period_label}` }))}
            plan={plan.slug}
            methods={methods.map((m) => ({ id: m.id, name: m.name }))}
          />
        ) : (
          <div className="card">Todavía no hay formas de pago disponibles. Escríbenos y te ayudamos.</div>
        )}
      </div>
    </div>
  );
}
