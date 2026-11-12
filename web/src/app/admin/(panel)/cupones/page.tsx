import { billingConfigured } from "@/lib/billing";
import { listCoupons } from "@/lib/coupons";
import { formatDate } from "@/lib/util";

import { couponCreateAction, couponToggleAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

export default async function CouponsPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const configured = billingConfigured();
  let coupons: Awaited<ReturnType<typeof listCoupons>> = [];
  let error = "";
  if (configured) {
    try {
      coupons = await listCoupons();
    } catch {
      error = "No se ha podido leer los cupones de Stripe ahora mismo.";
    }
  }
  return (
    <>
      <h1>Cupones</h1>
      <p className="muted">
        Códigos de descuento que el cliente escribe en la página de pago («Añadir código promocional»). Se guardan
        en Stripe: también los ves allí.
      </p>
      <Flash ok={ok} />
      {!configured ? (
        <div className="notice">Hace falta configurar Stripe (STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET) para crear cupones.</div>
      ) : (
        <>
          {error && <div className="notice">{error}</div>}
          <form action={couponCreateAction} className="card stack" style={{ maxWidth: 640 }}>
            <div className="two">
              <label>Código (lo que escribe el cliente)<input name="code" required maxLength={30} placeholder="FUNDADOR20" style={{ textTransform: "uppercase" }} /></label>
              <label>Descuento (%)<input name="percent" inputMode="numeric" required placeholder="20" /></label>
              <label>
                Duración
                <select name="duration" defaultValue="once">
                  <option value="once">Solo el primer pago</option>
                  <option value="repeating">Varios meses</option>
                  <option value="forever">Siempre</option>
                </select>
              </label>
              <label>Meses (si «varios meses»)<input name="months" inputMode="numeric" placeholder="3" /></label>
              <label>Usos máximos (vacío = sin límite)<input name="max" inputMode="numeric" /></label>
              <label>Caduca el (opcional)<input name="expires" type="date" /></label>
            </div>
            <div><button className="btn primary">Crear cupón</button></div>
          </form>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Código</th><th>Descuento</th><th>Usos</th><th>Caduca</th><th>Estado</th><th></th></tr></thead>
              <tbody>
                {coupons.map((c) => (
                  <tr key={c.id}>
                    <td><code>{c.code}</code></td>
                    <td>{c.description}</td>
                    <td>{c.used}{c.max ? ` / ${c.max}` : ""}</td>
                    <td>{c.expires ? formatDate(c.expires) : "—"}</td>
                    <td><span className={`badge ${c.active ? "ok" : "off"}`}>{c.active ? "activo" : "desactivado"}</span></td>
                    <td>
                      <form action={couponToggleAction}>
                        <input type="hidden" name="id" value={c.id} />
                        <input type="hidden" name="active" value={c.active ? "0" : "1"} />
                        <button className="btn small">{c.active ? "Desactivar" : "Activar"}</button>
                      </form>
                    </td>
                  </tr>
                ))}
                {coupons.length === 0 && <tr><td colSpan={6} className="muted">Aún no hay cupones.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
