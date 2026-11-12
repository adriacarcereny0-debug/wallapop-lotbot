"use server";

/**
 * Acciones de «Mi cuenta». Todas comprueban la sesión del cliente (salvo
 * entrar, registrarse y poner la contraseña con un enlace).
 */
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { createPortal, createSubscriptionCheckout, hasLiveSubscription } from "@/lib/billing";
import {
  changePassword,
  loginCustomer,
  logoutCustomer,
  registerCustomer,
  requireCustomer,
  setPasswordWithToken,
} from "@/lib/customer-auth";
import { db, logEvent } from "@/lib/db";
import { MAX_SELF_DEACTIVATIONS_PER_MONTH } from "@/lib/licensing";
import { getPlan } from "@/lib/store";
import { cleanEmail, cleanText, siteUrl } from "@/lib/util";

export type AccountFormState = {
  error?: string;
  ok?: string;
  needsKey?: boolean;
  /** Lo escrito (sin contraseñas), para no tener que repetirlo tras un error. */
  values?: Record<string, string>;
};

function kept(form: FormData, ...names: string[]): Record<string, string> {
  return Object.fromEntries(names.map((name) => [name, String(form.get(name) ?? "").slice(0, 200)]));
}

function safeNext(value: FormDataEntryValue | null): string {
  const next = String(value ?? "");
  return next.startsWith("/cuenta") && !next.startsWith("//") ? next : "/cuenta";
}

export async function loginAction(_prev: AccountFormState, form: FormData): Promise<AccountFormState> {
  const values = kept(form, "email");
  const email = cleanEmail(form.get("email"));
  if (!email) return { error: "Escribe un email válido.", values };
  const result = await loginCustomer(email, String(form.get("password") ?? ""));
  if (!result.ok) return { error: result.error, values };
  redirect(safeNext(form.get("next")));
}

export async function registerAction(_prev: AccountFormState, form: FormData): Promise<AccountFormState> {
  const values = kept(form, "name", "email", "license_key", "accept");
  const email = cleanEmail(form.get("email"));
  if (!email) return { error: "Escribe un email válido.", values };
  if (form.get("accept") !== "on") return { error: "Acepta los términos y la política de privacidad.", values };
  const password = String(form.get("password") ?? "");
  if (password !== String(form.get("password2") ?? "")) return { error: "Las dos contraseñas no coinciden.", values };
  const result = await registerCustomer({
    email,
    name: cleanText(form.get("name"), 120),
    password,
    licenseKey: cleanText(form.get("license_key"), 40),
  });
  if (!result.ok) return { error: result.error, needsKey: result.needsKey, values };
  redirect(safeNext(form.get("next")));
}

export async function setPasswordAction(_prev: AccountFormState, form: FormData): Promise<AccountFormState> {
  const password = String(form.get("password") ?? "");
  if (password !== String(form.get("password2") ?? "")) return { error: "Las dos contraseñas no coinciden." };
  const result = await setPasswordWithToken(String(form.get("token") ?? ""), password);
  if (!result.ok) return { error: result.error };
  redirect("/cuenta?ok=" + encodeURIComponent("Contraseña guardada."));
}

export async function changePasswordAction(_prev: AccountFormState, form: FormData): Promise<AccountFormState> {
  const customer = await requireCustomer();
  const next = String(form.get("password") ?? "");
  if (next !== String(form.get("password2") ?? "")) return { error: "Las dos contraseñas no coinciden." };
  const result = await changePassword(customer.id, String(form.get("current") ?? ""), next);
  if (!result.ok) return { error: result.error };
  return { ok: "Contraseña cambiada. Se han cerrado las demás sesiones." };
}

export async function logoutAction(): Promise<void> {
  await logoutCustomer();
  redirect("/cuenta/entrar");
}

export async function subscribeAction(form: FormData): Promise<void> {
  const customer = await requireCustomer();
  const plan = await getPlan(cleanText(form.get("plan"), 60));
  if (!plan || !plan.billing_interval) redirect("/cuenta?error=" + encodeURIComponent("Ese plan no está disponible."));
  if (await hasLiveSubscription(customer.id)) {
    redirect("/cuenta?error=" + encodeURIComponent("Ya tienes una suscripción. Gestiónala con «Pago y facturas»."));
  }
  let url: string;
  try {
    url = await createSubscriptionCheckout(customer.id, plan, siteUrl(await headers()));
  } catch (error) {
    console.error("Stripe:", error);
    redirect("/cuenta?error=" + encodeURIComponent("No se ha podido abrir el pago. Inténtalo en un momento."));
  }
  redirect(url);
}

export async function portalAction(): Promise<void> {
  const customer = await requireCustomer();
  let url: string;
  try {
    url = await createPortal(customer.id, `${siteUrl(await headers())}/cuenta`);
  } catch (error) {
    console.error("Stripe portal:", error);
    redirect("/cuenta?error=" + encodeURIComponent("No se ha podido abrir la gestión del pago. Inténtalo en un momento."));
  }
  redirect(url);
}

/** Desvincular uno de SUS ordenadores (mismo límite que desde el programa). */
export async function unlinkDeviceAction(form: FormData): Promise<void> {
  const customer = await requireCustomer();
  const deviceId = Number(form.get("device"));
  const sql = await db();
  const [device] = await sql<{ id: number; license_id: number; fingerprint: string; key: string }[]>`
    SELECT d.id, d.license_id, d.fingerprint, l.key FROM lotbot.devices d
    JOIN lotbot.licenses l ON l.id = d.license_id
    WHERE d.id = ${deviceId} AND l.customer_id = ${customer.id} AND d.status = 'activo'
  `;
  if (!device) redirect("/cuenta");
  const [{ count }] = await sql<{ count: number }[]>`
    SELECT count(*)::int AS count FROM lotbot.license_events
    WHERE license_id = ${device.license_id} AND kind = 'desvinculado_por_cliente' AND at > now() - interval '30 days'
  `;
  if (count >= MAX_SELF_DEACTIVATIONS_PER_MONTH) {
    redirect(
      "/cuenta?error=" +
        encodeURIComponent(`Solo puedes cambiar de ordenador ${MAX_SELF_DEACTIVATIONS_PER_MONTH} veces al mes. Escríbenos y te ayudamos.`),
    );
  }
  await sql`UPDATE lotbot.devices SET status = 'desvinculado' WHERE id = ${device.id}`;
  await sql`
    INSERT INTO lotbot.license_events (license_id, kind, fingerprint, detail)
    VALUES (${device.license_id}, 'desvinculado_por_cliente', ${device.fingerprint}, 'desde Mi cuenta')
  `;
  await logEvent("Ordenador desvinculado desde Mi cuenta", `${customer.email} · ${device.key}`, "cliente");
  redirect("/cuenta?ok=" + encodeURIComponent("Ordenador desvinculado: ya puedes activar la licencia en otro."));
}
