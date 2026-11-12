/**
 * Pago con tarjeta mediante Stripe Checkout (opcional).
 *
 * Solo se ofrece si están STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET. La
 * página de pago la muestra Stripe: LOT Bot nunca ve ni guarda los datos de
 * la tarjeta. Cuando Stripe confirma el pago (webhook), el pedido pasa a
 * «pagado» y se crea la licencia.
 */
import Stripe from "stripe";

import type { Order, Plan } from "./store";

let client: Stripe | null = null;

export function stripe(): Stripe {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) throw new Error("Falta STRIPE_SECRET_KEY.");
  client ??= new Stripe(key);
  return client;
}

/** Solo para comprobar la firma de los avisos (no llama a Stripe). */
export function webhookVerifier(): Stripe {
  return process.env.STRIPE_SECRET_KEY ? stripe() : new Stripe("sk_test_solo_para_firmas");
}

export async function createCheckout(
  order: Order,
  plan: Plan,
  email: string,
  baseUrl: string,
): Promise<{ id: string; url: string }> {
  const session = await stripe().checkout.sessions.create({
    mode: "payment",
    customer_email: email,
    client_reference_id: order.reference,
    metadata: { order_reference: order.reference },
    line_items: [
      {
        quantity: 1,
        price_data: {
          currency: plan.currency.toLowerCase(),
          unit_amount: plan.price_cents,
          product_data: { name: `LOT Bot · ${plan.name}`, description: plan.description || undefined },
        },
      },
    ],
    success_url: `${baseUrl}/pedido/${order.reference}?pago=ok`,
    cancel_url: `${baseUrl}/pedido/${order.reference}?pago=cancelado`,
  });
  if (!session.url) throw new Error("Stripe no ha devuelto la página de pago.");
  return { id: session.id, url: session.url };
}
