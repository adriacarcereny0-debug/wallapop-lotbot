import { listPlans, plansAreExamples, type Plan } from "@/lib/store";
import { formatMoney } from "@/lib/util";

import { deletePlanAction, savePlanAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

function PlanForm({ plan }: { plan?: Plan }) {
  return (
    <form action={savePlanAction} className="stack">
      {plan && <input type="hidden" name="id" value={plan.id} />}
      <div className="two">
        <label>Nombre<input name="name" defaultValue={plan?.name} required placeholder="Mensual" /></label>
        <label>Identificador (en la dirección)<input name="slug" defaultValue={plan?.slug} required placeholder="mensual" /></label>
        <label>Precio<input name="price" inputMode="decimal" defaultValue={plan ? String(plan.price_cents / 100).replace(".", ",") : ""} required placeholder="29" /></label>
        <label>Moneda<input name="currency" defaultValue={plan?.currency ?? "EUR"} maxLength={3} /></label>
        <label>Se muestra «/ …»<input name="period_label" defaultValue={plan?.period_label ?? "mes"} placeholder="mes, 3 meses, año, pago único" /></label>
        <label>Días de licencia (vacío = sin caducidad)<input name="duration_days" inputMode="numeric" defaultValue={plan?.duration_days ?? ""} /></label>
        <label>Ordenadores por licencia<input name="max_devices" inputMode="numeric" defaultValue={plan?.max_devices ?? 1} /></label>
        <label>Orden<input name="sort" inputMode="numeric" defaultValue={plan?.sort ?? 0} /></label>
      </div>
      <label>Descripción corta<input name="description" defaultValue={plan?.description} /></label>
      <label>Lo que incluye (una línea por punto)<textarea name="features" defaultValue={plan?.features.join("\n")} /></label>
      <div className="toolbar">
        <label className="check"><input type="checkbox" name="active" defaultChecked={plan?.active ?? true} /> Visible en la web</label>
        <label className="check"><input type="checkbox" name="highlighted" defaultChecked={plan?.highlighted ?? false} /> Destacado («El más elegido»)</label>
        <button className="btn primary">{plan ? "Guardar" : "Crear plan"}</button>
      </div>
    </form>
  );
}

export default async function PlansPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const plans = await listPlans(false);
  const examples = await plansAreExamples();
  return (
    <>
      <h1>Planes y precios</h1>
      <p className="muted">Lo que ven los clientes en «Precios». Los cambios se ven en la web al momento.</p>
      {examples && <div className="notice">Estos planes y precios son de EJEMPLO. Cámbialos por los tuyos (al guardar cualquiera desaparece este aviso).</div>}
      <Flash ok={ok} />
      {plans.map((plan) => (
        <details className="card" key={plan.id} style={{ margin: "14px 0" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>
            {plan.name} · {formatMoney(plan.price_cents, plan.currency)} / {plan.period_label}{" "}
            <span className={`badge ${plan.active ? "ok" : "off"}`}>{plan.active ? "visible" : "oculto"}</span>
          </summary>
          <div style={{ marginTop: 16 }}>
            <PlanForm plan={plan} />
            <form action={deletePlanAction} style={{ marginTop: 10 }}>
              <input type="hidden" name="id" value={plan.id} />
              <button className="btn small danger">Borrar plan</button>
            </form>
          </div>
        </details>
      ))}
      <details className="card" style={{ margin: "14px 0" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>+ Nuevo plan</summary>
        <div style={{ marginTop: 16 }}><PlanForm /></div>
      </details>
    </>
  );
}
