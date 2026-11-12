/** Cupones de descuento (códigos promocionales de Stripe). */
import { stripe } from "./stripe";

export type CouponRow = {
  id: string;
  code: string;
  description: string;
  used: number;
  max: number | null;
  expires: Date | null;
  active: boolean;
};

export async function listCoupons(): Promise<CouponRow[]> {
  const list = await stripe().promotionCodes.list({ limit: 100, expand: ["data.coupon"] });
  return list.data.map((p) => {
    const coupon = (p as unknown as { coupon?: { percent_off?: number | null; duration?: string; duration_in_months?: number | null } }).coupon ?? {};
    const how = coupon.duration === "forever" ? "siempre" : coupon.duration === "repeating" ? `${coupon.duration_in_months} meses` : "primer pago";
    return {
      id: p.id,
      code: p.code,
      description: `${coupon.percent_off ?? "?"} % · ${how}`,
      used: p.times_redeemed,
      max: p.max_redemptions ?? null,
      expires: p.expires_at ? new Date(p.expires_at * 1000) : null,
      active: p.active,
    };
  });
}

export type CouponInput = {
  code: string;
  percent: number;
  duration: "once" | "repeating" | "forever";
  months: number | null;
  max: number | null;
  expires: Date | null;
};

export function couponProblem(input: CouponInput): string | null {
  if (!/^[A-Z0-9]{3,30}$/.test(input.code)) return "El código: de 3 a 30 letras y números (sin espacios ni símbolos).";
  if (!(input.percent > 0 && input.percent <= 100)) return "El descuento va de 1 a 100 %.";
  if (input.duration === "repeating" && !(input.months && input.months >= 1 && input.months <= 36)) return "Indica de 1 a 36 meses.";
  if (input.max != null && !(input.max >= 1)) return "Usos máximos: 1 o más.";
  if (input.expires && input.expires.getTime() <= Date.now()) return "La fecha de caducidad ya ha pasado.";
  return null;
}

export async function createCoupon(input: CouponInput): Promise<void> {
  const client = stripe();
  const coupon = await client.coupons.create({
    percent_off: input.percent,
    duration: input.duration,
    duration_in_months: input.duration === "repeating" ? input.months ?? undefined : undefined,
    name: input.code,
  });
  await client.promotionCodes.create({
    coupon: coupon.id,
    code: input.code,
    max_redemptions: input.max ?? undefined,
    expires_at: input.expires ? Math.floor(input.expires.getTime() / 1000) : undefined,
  });
}

export async function setCouponActive(id: string, active: boolean): Promise<void> {
  await stripe().promotionCodes.update(id, { active });
}
