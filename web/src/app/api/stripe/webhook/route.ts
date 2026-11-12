import { NextResponse } from "next/server";
import type Stripe from "stripe";

import { syncSubscription, type SubscriptionLike } from "@/lib/billing";
import { db } from "@/lib/db";
import { webhookVerifier } from "@/lib/stripe";
import { markOrderPaid } from "@/lib/store";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const SUBSCRIPTION_EVENTS = new Set([
  "customer.subscription.created",
  "customer.subscription.updated",
  "customer.subscription.deleted",
  "customer.subscription.paused",
  "customer.subscription.resumed",
]);

/**
 * Stripe avisa aquí: pagos sueltos (pedidos antiguos) y suscripciones.
 * Cada aviso se procesa una sola vez; si algo falla se devuelve 500 y Stripe
 * lo reintenta más tarde.
 */
export async function POST(request: Request) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  const signature = request.headers.get("stripe-signature");
  if (!secret || !signature) return NextResponse.json({ error: "Sin firma." }, { status: 400 });
  const payload = await request.text();
  let event: Stripe.Event;
  try {
    event = webhookVerifier().webhooks.constructEvent(payload, signature, secret);
  } catch {
    return NextResponse.json({ error: "Firma no válida." }, { status: 400 });
  }

  const sql = await db();
  const fresh = await sql`
    INSERT INTO lotbot.stripe_events (id, type) VALUES (${event.id}, ${event.type})
    ON CONFLICT (id) DO NOTHING RETURNING id
  `;
  if (!fresh.length) return NextResponse.json({ received: true, duplicate: true });

  try {
    if (SUBSCRIPTION_EVENTS.has(event.type)) {
      await syncSubscription(event.data.object as unknown as SubscriptionLike, event.created);
    } else if (
      event.type === "checkout.session.completed" ||
      event.type === "checkout.session.async_payment_succeeded"
    ) {
      const session = event.data.object as Stripe.Checkout.Session;
      if (session.mode === "subscription") {
        // La licencia la crean los avisos de la suscripción; aquí solo se
        // vincula el cliente de Stripe con el nuestro.
        const customerId = Number(session.client_reference_id || session.metadata?.customer_id);
        const stripeCustomer = typeof session.customer === "string" ? session.customer : session.customer?.id;
        if (customerId && stripeCustomer) {
          await sql`
            UPDATE lotbot.customers SET stripe_customer_id = ${stripeCustomer}
            WHERE id = ${customerId} AND stripe_customer_id IS NULL
          `;
        }
      } else if (session.payment_status === "paid") {
        const reference = session.metadata?.order_reference || session.client_reference_id;
        const rows = await sql<{ id: number; amount_cents: number }[]>`
          SELECT id, amount_cents FROM lotbot.orders WHERE reference = ${reference ?? ""}
        `;
        if (rows.length && (session.amount_total ?? 0) >= rows[0].amount_cents) {
          await markOrderPaid(rows[0].id, "stripe");
        }
      }
    }
  } catch (error) {
    console.error("Aviso de Stripe", event.id, event.type, error);
    await sql`DELETE FROM lotbot.stripe_events WHERE id = ${event.id}`;
    return NextResponse.json({ error: "No se ha podido procesar." }, { status: 500 });
  }
  return NextResponse.json({ received: true });
}
