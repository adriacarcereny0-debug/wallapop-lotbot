import { NextResponse } from "next/server";

import { db } from "@/lib/db";
import { stripe } from "@/lib/stripe";
import { markOrderPaid } from "@/lib/store";

export const dynamic = "force-dynamic";

/** Stripe avisa aquí cuando un pago con tarjeta se completa. */
export async function POST(request: Request) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  const signature = request.headers.get("stripe-signature");
  if (!secret || !signature) return NextResponse.json({ error: "Sin firma." }, { status: 400 });
  const payload = await request.text();
  let event;
  try {
    event = stripe().webhooks.constructEvent(payload, signature, secret);
  } catch {
    return NextResponse.json({ error: "Firma no válida." }, { status: 400 });
  }
  if (event.type === "checkout.session.completed" || event.type === "checkout.session.async_payment_succeeded") {
    const session = event.data.object;
    if (session.payment_status === "paid") {
      const reference = session.metadata?.order_reference || session.client_reference_id;
      const sql = await db();
      const rows = await sql<{ id: number; amount_cents: number }[]>`
        SELECT id, amount_cents FROM lotbot.orders WHERE reference = ${reference ?? ""}
      `;
      if (rows.length && (session.amount_total ?? 0) >= rows[0].amount_cents) {
        await markOrderPaid(rows[0].id, "stripe");
      }
    }
  }
  return NextResponse.json({ received: true });
}
