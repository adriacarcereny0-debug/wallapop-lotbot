import { NextResponse } from "next/server";

import { db } from "@/lib/db";
import { createSubscriptionCheckout, hasLiveSubscription } from "@/lib/billing";
import { createCheckout } from "@/lib/stripe";
import { createOrder, getPlan, publicPaymentMethods, upsertCustomer } from "@/lib/store";
import { cleanEmail, cleanText, siteUrl } from "@/lib/util";

export const dynamic = "force-dynamic";

/** Crea el pedido. Con tarjeta devuelve la página de pago de Stripe; con
 * Bizum, transferencia o PayPal, la referencia y las instrucciones. */
export async function POST(request: Request) {
  let body: Record<string, unknown> = {};
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Datos no válidos." }, { status: 400 });
  }
  const email = cleanEmail(body.email);
  if (!email) return NextResponse.json({ ok: false, error: "Escribe un email válido." }, { status: 400 });
  if (body.accept !== true) {
    return NextResponse.json({ ok: false, error: "Acepta la política de privacidad para continuar." }, { status: 400 });
  }
  const plan = await getPlan(cleanText(body.plan, 60));
  if (!plan) return NextResponse.json({ ok: false, error: "Ese plan no está disponible." }, { status: 400 });
  const methods = await publicPaymentMethods();
  const method = methods.find((m) => m.id === cleanText(body.method, 40));
  if (!method) return NextResponse.json({ ok: false, error: "Elige una forma de pago." }, { status: 400 });

  // Con tarjeta y un plan mensual o anual: suscripción (se renueva sola).
  if (method.id === "tarjeta" && plan.billing_interval) {
    try {
      // Si el email ya es cliente (tiene cuenta o alguna licencia), se suscribe
      // desde «Mi cuenta»: así nadie paga con el email de otro para quedarse
      // con su licencia.
      const sql = await db();
      const known = await sql`
        SELECT 1 FROM lotbot.customers c
        WHERE c.email = ${email}
          AND (c.password_hash IS NOT NULL OR EXISTS (SELECT 1 FROM lotbot.licenses l WHERE l.customer_id = c.id))
      `;
      if (known.length) {
        return NextResponse.json(
          {
            ok: false,
            error: "Ese email ya es cliente de LOT Bot. Entra en «Mi cuenta» (o créala con tu clave de licencia) para suscribirte y conservar tu clave.",
            redirect: "/cuenta/entrar",
          },
          { status: 409 },
        );
      }
      const customerId = await upsertCustomer(email, cleanText(body.name, 120), cleanText(body.phone, 40));
      if (await hasLiveSubscription(customerId)) {
        return NextResponse.json(
          { ok: false, error: "Ese email ya tiene una suscripción. Entra en «Mi cuenta» para gestionarla." },
          { status: 409 },
        );
      }
      const url = await createSubscriptionCheckout(customerId, plan, siteUrl(request.headers));
      return NextResponse.json({ ok: true, redirect: url });
    } catch (error) {
      console.error("Stripe:", error);
      return NextResponse.json(
        { ok: false, error: "No se ha podido abrir el pago con tarjeta. Prueba otra forma de pago." },
        { status: 502 },
      );
    }
  }

  const order = await createOrder({
    plan,
    method: method.id,
    email,
    name: cleanText(body.name, 120),
    phone: cleanText(body.phone, 40),
  });
  if (method.id === "tarjeta") {
    try {
      const checkout = await createCheckout(order, plan, email, siteUrl(request.headers));
      const sql = await db();
      await sql`UPDATE lotbot.orders SET stripe_session_id = ${checkout.id} WHERE id = ${order.id}`;
      return NextResponse.json({ ok: true, reference: order.reference, redirect: checkout.url });
    } catch (error) {
      console.error("Stripe:", error);
      return NextResponse.json(
        { ok: false, error: "No se ha podido abrir el pago con tarjeta. Prueba otra forma de pago." },
        { status: 502 },
      );
    }
  }
  return NextResponse.json({ ok: true, reference: order.reference, redirect: `/pedido/${order.reference}` });
}
