import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { fulfillCheckout } from "@/lib/billing";
import { createPasswordToken, currentCustomer } from "@/lib/customer-auth";
import { db } from "@/lib/db";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "¡Bienvenido a LOT Bot!", robots: { index: false } };

/**
 * Vuelta del pago de Stripe. Se comprueba el pago con Stripe y se aplica ya
 * (no se espera al aviso). Si el cliente aún no tiene contraseña (pagó sin
 * cuenta), se le lleva a ponerla: el enlace solo sirve una vez.
 */
export default async function WelcomePage({ searchParams }: { searchParams: Promise<{ session_id?: string }> }) {
  const { session_id: sessionId = "" } = await searchParams;
  let result: Awaited<ReturnType<typeof fulfillCheckout>> = null;
  try {
    result = await fulfillCheckout(sessionId);
  } catch (error) {
    console.error("Vuelta de Stripe:", error);
  }
  if (!result) {
    return (
      <div className="form-page">
        <div className="wrap panel card stack">
          <h1 className="title" style={{ fontSize: 30 }}>Estamos confirmando tu pago</h1>
          <p className="muted">Stripe aún no nos lo ha confirmado. Espera un minuto y entra en <Link href="/cuenta">Mi cuenta</Link>.</p>
        </div>
      </div>
    );
  }
  const sql = await db();
  const [customer] = await sql<{ email: string; has_password: boolean }[]>`
    SELECT email, password_hash IS NOT NULL AS has_password FROM lotbot.customers WHERE id = ${result.customerId}
  `;
  const [license] = result.licenseId
    ? await sql<{ key: string }[]>`SELECT key FROM lotbot.licenses WHERE id = ${result.licenseId}`
    : [];
  const session = await currentCustomer();
  if (session && session.id === result.customerId) {
    redirect("/cuenta?ok=" + encodeURIComponent("¡Suscripción activada! Tu licencia ya funciona."));
  }
  const token = customer && !customer.has_password ? await createPasswordToken(result.customerId, 2) : null;
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Pago completado</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0 14px" }}>¡Bienvenido a LOT Bot!</h1>
        <div className="card stack">
          {license ? (
            <>
              <p style={{ margin: 0 }}>Tu clave de licencia:</p>
              <div className="keybox">{license.key}</div>
              <p className="faint" style={{ margin: 0 }}>Escríbela en LOT Bot → Configuración → Licencia. Guárdala bien.</p>
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>Tu licencia se está creando; la verás en Mi cuenta en unos segundos.</p>
          )}
          {token ? (
            <>
              <p style={{ margin: "8px 0 0" }}>
                Último paso: pon una contraseña para <b>{customer.email}</b>. Con ella entras en Mi cuenta para ver tu
                licencia, tus ordenadores y gestionar el pago.
              </p>
              <Link className="btn primary" href={`/cuenta/clave?token=${encodeURIComponent(token)}`}>Poner mi contraseña</Link>
            </>
          ) : (
            <Link className="btn primary" href="/cuenta/entrar">Entrar en Mi cuenta</Link>
          )}
        </div>
      </div>
    </div>
  );
}
