import { allPaymentMethods, stripeConfigured } from "@/lib/store";
import { siteUrl } from "@/lib/util";

import { savePaymentMethodAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

const EXAMPLES: Record<string, string> = {
  bizum: "Envía un Bizum de {importe} al 600 000 000 (Nombre Apellido) con el concepto {referencia}.",
  transferencia: "Transfiere {importe} a la cuenta ES00 0000 0000 0000 0000 0000 (Nombre Apellido) con el concepto {referencia}.",
  paypal: "Paga {importe} en https://paypal.me/tuusuario e indica {referencia} en la nota.",
};

export default async function PaymentsPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const methods = await allPaymentMethods();
  const stripe = stripeConfigured();
  return (
    <>
      <h1>Formas de pago</h1>
      <p className="muted">
        Solo se ofrecen las activadas y listas. En las instrucciones puedes usar <code>{"{importe}"}</code> y{" "}
        <code>{"{referencia}"}</code>: se cambian por los del pedido.
      </p>
      <Flash ok={ok} />
      {methods.map((m) => {
        const ready = m.id === "tarjeta" ? stripe : m.instructions.trim() !== "";
        return (
          <div className="card" key={m.id} style={{ margin: "14px 0" }}>
            <form action={savePaymentMethodAction} className="stack">
              <input type="hidden" name="id" value={m.id} />
              <div className="toolbar" style={{ margin: 0 }}>
                <label style={{ flex: 1 }}>Nombre que ve el cliente<input name="name" defaultValue={m.name} /></label>
                <label className="check"><input type="checkbox" name="enabled" defaultChecked={m.enabled} /> Activada</label>
                <span className={`badge ${m.enabled && ready ? "ok" : "off"}`}>
                  {m.enabled && ready ? "Se ofrece" : m.enabled ? "Falta configurarla" : "Desactivada"}
                </span>
              </div>
              {m.id === "tarjeta" ? (
                <div className="muted">
                  {stripe ? (
                    "Stripe está configurado: el pago se confirma y la licencia se crea solos."
                  ) : (
                    <>
                      Para cobrar con tarjeta: crea una cuenta en stripe.com y pon en Vercel{" "}
                      <code>STRIPE_SECRET_KEY</code> y <code>STRIPE_WEBHOOK_SECRET</code>. El webhook de Stripe debe
                      apuntar a <code>{siteUrl()}/api/stripe/webhook</code> con el evento{" "}
                      <code>checkout.session.completed</code>.
                    </>
                  )}
                  <input type="hidden" name="instructions" value="" />
                </div>
              ) : (
                <label>
                  Instrucciones de pago (las ve el cliente tras hacer el pedido)
                  <textarea name="instructions" defaultValue={m.instructions} placeholder={EXAMPLES[m.id]} />
                </label>
              )}
              <div><button className="btn small primary">Guardar</button></div>
            </form>
          </div>
        );
      })}
    </>
  );
}
