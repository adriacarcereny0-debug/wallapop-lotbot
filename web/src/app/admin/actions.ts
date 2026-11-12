"use server";

/**
 * Acciones del panel /admin. Todas comprueban primero la sesión.
 */
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { headers } from "next/headers";

import { login, logout, requireAdmin } from "@/lib/auth";
import { createPasswordToken } from "@/lib/customer-auth";
import { confirmSetup, disable, startSetup } from "@/lib/totp";
import { couponProblem, createCoupon, setCouponActive, type CouponInput } from "@/lib/coupons";
import { db, logEvent, setSetting } from "@/lib/db";
import { issueLicense, markOrderPaid, siteSettings, upsertCustomer } from "@/lib/store";
import { cleanEmail, cleanText, siteUrl } from "@/lib/util";

export type FormState = { error?: string; ok?: string };

function num(value: FormDataEntryValue | null, fallback: number | null = null): number | null {
  const text = String(value ?? "").trim().replace(",", ".");
  if (text === "") return fallback;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function back(path: string, message?: string): never {
  revalidatePath(path);
  redirect(message ? `${path}?ok=${encodeURIComponent(message)}` : path);
}

// --- Sesión -----------------------------------------------------------------
export async function loginAction(_prev: FormState, form: FormData): Promise<FormState> {
  const result = await login(String(form.get("password") ?? ""), String(form.get("code") ?? ""));
  if (!result.ok) return { error: result.error };
  redirect("/admin");
}

export async function logoutAction(): Promise<void> {
  await logout();
  redirect("/admin/login");
}

// --- Pedidos ----------------------------------------------------------------
export async function markPaidAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = num(form.get("id"));
  if (id) await markOrderPaid(id, "admin");
  back("/admin/pedidos", "Pedido marcado como pagado: licencia creada.");
}

export async function cancelOrderAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = num(form.get("id"));
  const sql = await db();
  const rows = await sql<{ reference: string }[]>`
    UPDATE lotbot.orders SET status = 'cancelado' WHERE id = ${id} AND status = 'pendiente' RETURNING reference
  `;
  if (rows.length) await logEvent("Pedido cancelado", rows[0].reference, "admin");
  back("/admin/pedidos", "Pedido cancelado.");
}

export async function orderNotesAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  await sql`UPDATE lotbot.orders SET notes = ${cleanText(form.get("notes"), 500)} WHERE id = ${num(form.get("id"))}`;
  back("/admin/pedidos", "Nota guardada.");
}

// --- Licencias --------------------------------------------------------------
export async function createLicenseAction(form: FormData): Promise<void> {
  await requireAdmin();
  const email = cleanEmail(form.get("email"));
  if (!email) back("/admin/licencias", "⚠ Escribe un email válido.");
  const sql = await db();
  const planId = num(form.get("plan_id"));
  const [plan] = planId ? await sql<{ duration_days: number | null; max_devices: number }[]>`
    SELECT duration_days, max_devices FROM lotbot.plans WHERE id = ${planId}` : [];
  const days = num(form.get("days"), plan ? plan.duration_days : null);
  const customerId = await upsertCustomer(email, cleanText(form.get("name"), 120), cleanText(form.get("phone"), 40));
  const license = await issueLicense({
    customerId,
    kind: "manual",
    planId,
    durationDays: days && days > 0 ? Math.round(days) : null,
    maxDevices: Math.max(1, Math.min(20, num(form.get("max_devices"), plan?.max_devices ?? 1) ?? 1)),
    notes: cleanText(form.get("notes"), 500),
  });
  await logEvent("Licencia creada a mano", `${email} → ${license.key}`, "admin");
  back("/admin/licencias", `Licencia creada: ${license.key}`);
}

export async function extendLicenseAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = num(form.get("id"));
  const days = Math.round(num(form.get("days"), 30) ?? 30);
  const sql = await db();
  const rows = await sql<{ key: string }[]>`
    UPDATE lotbot.licenses SET
      expires_at = GREATEST(COALESCE(expires_at, now()), now()) + make_interval(days => ${days}),
      status = 'activa'
    WHERE id = ${id} RETURNING key
  `;
  if (rows.length) await logEvent("Licencia ampliada", `${rows[0].key} +${days} días`, "admin");
  back("/admin/licencias", `Ampliada ${days} días.`);
}

/** Cambia el estado: activa, suspendida (con motivo, reversible) o revocada (definitiva). */
export async function setLicenseStatusAction(form: FormData): Promise<void> {
  await requireAdmin();
  const status = cleanText(form.get("status"), 20);
  if (!["activa", "suspendida", "revocada"].includes(status)) back("/admin/licencias");
  const reason = status === "activa" ? "" : cleanText(form.get("reason"), 200);
  const sql = await db();
  const rows = await sql<{ key: string }[]>`
    UPDATE lotbot.licenses SET status = ${status}, status_reason = ${reason}, updated_at = now()
    WHERE id = ${num(form.get("id"))} RETURNING key
  `;
  if (rows.length) {
    await logEvent(`Licencia ${status}`, `${rows[0].key}${reason ? ` · ${reason}` : ""}`, "admin");
  }
  const label = { activa: "activada", suspendida: "suspendida", revocada: "revocada" }[status];
  back(
    cleanText(form.get("back"), 200) || "/admin/licencias",
    rows.length ? `Licencia ${label}. LOT Bot lo aplica en su próxima comprobación (como mucho, al caducar su pase de 72 h).` : undefined,
  );
}

export async function resetDevicesAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const id = num(form.get("id"));
  await sql`UPDATE lotbot.devices SET status = 'desvinculado' WHERE license_id = ${id} AND status = 'activo'`;
  await logEvent("Ordenadores de la licencia desvinculados", String(id), "admin");
  back("/admin/licencias", "Ordenadores desvinculados: podrá activarse en uno nuevo.");
}

/** Dispositivo: desvincular (libera la plaza), bloquear o desbloquear. */
export async function setDeviceStatusAction(form: FormData): Promise<void> {
  await requireAdmin();
  const status = cleanText(form.get("status"), 20);
  if (!["activo", "desvinculado", "bloqueado"].includes(status)) back("/admin/dispositivos");
  const sql = await db();
  const rows = await sql<{ fingerprint: string; key: string }[]>`
    UPDATE lotbot.devices d SET status = ${status} FROM lotbot.licenses l
    WHERE d.id = ${num(form.get("id"))} AND l.id = d.license_id
    RETURNING d.fingerprint, l.key
  `;
  if (rows.length) {
    await logEvent(`Dispositivo ${status}`, `${rows[0].key} · ${rows[0].fingerprint.slice(0, 12)}…`, "admin");
  }
  back("/admin/dispositivos", rows.length ? `Dispositivo ${status}.` : undefined);
}

// --- Clientes ---------------------------------------------------------------
export async function setFounderAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const founder = form.get("founder") === "1";
  const rows = await sql<{ email: string }[]>`
    UPDATE lotbot.customers SET founder = ${founder} WHERE id = ${num(form.get("id"))} RETURNING email
  `;
  if (rows.length) await logEvent(founder ? "Cliente fundador" : "Cliente ya no es fundador", rows[0].email, "admin");
  back("/admin/clientes", founder ? "Marcado como fundador: pagará el precio de fundador al suscribirse." : "Ya no es fundador.");
}

export async function setBetaAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const beta = form.get("beta") === "1";
  const rows = await sql<{ email: string }[]>`
    UPDATE lotbot.customers SET beta = ${beta} WHERE id = ${num(form.get("id"))} RETURNING email
  `;
  if (rows.length) await logEvent(beta ? "Cliente en canal beta" : "Cliente fuera del canal beta", rows[0].email, "admin");
  back("/admin/clientes", beta ? "Recibirá también las versiones beta." : "Solo recibirá versiones estables.");
}

/** Alta de los clientes actuales: fundador + licencia + mensaje para enviar. */
export async function launchImportAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const planSlug = cleanText(form.get("plan"), 40);
  const [plan] = await sql<{ id: number; max_devices: number; name: string }[]>`
    SELECT id, max_devices, name FROM lotbot.plans WHERE slug = ${planSlug}`;
  const days = Math.max(1, Math.min(3650, Math.round(num(form.get("days"), 30) ?? 30)));
  const lines = String(form.get("clients") ?? "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(0, 200);
  let created = 0;
  const problems: string[] = [];
  for (const line of lines) {
    const [rawEmail, ...rest] = line.split(/[;,\t]/);
    const email = cleanEmail(rawEmail);
    if (!email) {
      problems.push(line);
      continue;
    }
    const customerId = await upsertCustomer(email, cleanText(rest.join(" "), 120));
    await sql`UPDATE lotbot.customers SET founder = true WHERE id = ${customerId}`;
    const existing = await sql`
      SELECT 1 FROM lotbot.licenses WHERE customer_id = ${customerId} AND notes = 'Lanzamiento (cliente fundador)'`;
    if (existing.length) continue; // ya importado: no se duplica
    await issueLicense({
      customerId, kind: "manual", planId: plan?.id ?? null, durationDays: days,
      maxDevices: plan?.max_devices ?? 1, notes: "Lanzamiento (cliente fundador)",
    });
    created++;
  }
  await logEvent("Alta de clientes fundadores", `${created} licencias (${days} días)`, "admin");
  back(
    "/admin/lanzamiento",
    `${created} licencia${created === 1 ? "" : "s"} creada${created === 1 ? "" : "s"}.` +
      (problems.length ? ` ⚠ Líneas sin email válido: ${problems.slice(0, 5).join(" | ")}` : ""),
  );
}

/** Enlace de un solo uso (48 h) para que el cliente ponga o cambie su contraseña. */
export async function passwordLinkAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = num(form.get("id"));
  const sql = await db();
  const [customer] = await sql<{ email: string }[]>`SELECT email FROM lotbot.customers WHERE id = ${id}`;
  if (!customer) back("/admin/clientes");
  const token = await createPasswordToken(id as number);
  const link = `${siteUrl(await headers())}/cuenta/clave?token=${token}`;
  await logEvent("Enlace de contraseña creado", customer.email, "admin");
  back("/admin/clientes", `Enlace para ${customer.email} (vale 48 h, un solo uso): ${link}`);
}

// --- Versiones ---------------------------------------------------------------
export async function releaseUpdateAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = num(form.get("id"));
  const op = cleanText(form.get("op"), 20);
  const sql = await db();
  let rows: { version: string; platform: string }[] = [];
  if (op === "rollout") {
    const percent = Math.max(0, Math.min(100, Math.round(num(form.get("rollout"), 100) ?? 100)));
    rows = await sql`UPDATE lotbot.releases SET rollout_percent = ${percent} WHERE id = ${id} RETURNING version, platform`;
    if (rows.length) await logEvent("Despliegue de versión", `${rows[0].version} ${rows[0].platform} → ${percent} %`, "admin");
  } else if (op === "retire" || op === "restore") {
    const status = op === "retire" ? "retirada" : "activa";
    rows = await sql`UPDATE lotbot.releases SET status = ${status} WHERE id = ${id} RETURNING version, platform`;
    if (rows.length) await logEvent(`Versión ${status}`, `${rows[0].version} ${rows[0].platform}`, "admin");
  } else if (op === "mandatory") {
    rows = await sql`UPDATE lotbot.releases SET mandatory = NOT mandatory WHERE id = ${id} RETURNING version, platform`;
    if (rows.length) await logEvent("Versión obligatoria (cambio)", `${rows[0].version} ${rows[0].platform}`, "admin");
  }
  back("/admin/versiones", rows.length ? "Versión actualizada." : undefined);
}

// --- Seguridad (verificación en dos pasos) ---------------------------------------
export async function twoFactorStartAction(): Promise<void> {
  await requireAdmin();
  await startSetup();
  back("/admin/seguridad");
}

export async function twoFactorConfirmAction(form: FormData): Promise<void> {
  await requireAdmin();
  const ok = await confirmSetup(cleanText(form.get("code"), 10));
  if (ok) await logEvent("Verificación en dos pasos activada", "", "admin");
  back("/admin/seguridad", ok ? "Verificación en dos pasos activada." : "⚠ Código incorrecto. Revisa la hora del móvil y vuelve a probar.");
}

export async function twoFactorDisableAction(form: FormData): Promise<void> {
  await requireAdmin();
  const ok = await disable(cleanText(form.get("code"), 10));
  if (ok) await logEvent("Verificación en dos pasos desactivada", "", "admin");
  back("/admin/seguridad", ok ? "Verificación en dos pasos desactivada." : "⚠ Código incorrecto.");
}

// --- Cupones ----------------------------------------------------------------
export async function couponCreateAction(form: FormData): Promise<void> {
  await requireAdmin();
  const duration = cleanText(form.get("duration"), 20);
  const expiresText = cleanText(form.get("expires"), 10);
  const input: CouponInput = {
    code: cleanText(form.get("code"), 30).toUpperCase(),
    percent: num(form.get("percent"), 0) ?? 0,
    duration: (["once", "repeating", "forever"].includes(duration) ? duration : "once") as CouponInput["duration"],
    months: num(form.get("months")),
    max: num(form.get("max")),
    expires: expiresText ? new Date(`${expiresText}T23:59:59`) : null,
  };
  const problem = couponProblem(input);
  if (problem) back("/admin/cupones", `⚠ ${problem}`);
  try {
    await createCoupon(input);
  } catch (error) {
    console.error("Cupón:", error);
    back("/admin/cupones", "⚠ Stripe no ha aceptado el cupón (¿ya existe ese código?).");
  }
  await logEvent("Cupón creado", `${input.code} · ${input.percent} %`, "admin");
  back("/admin/cupones", `Cupón ${input.code} creado.`);
}

export async function couponToggleAction(form: FormData): Promise<void> {
  await requireAdmin();
  const id = cleanText(form.get("id"), 80);
  const active = form.get("active") === "1";
  try {
    await setCouponActive(id, active);
  } catch (error) {
    console.error("Cupón:", error);
    back("/admin/cupones", "⚠ No se ha podido cambiar en Stripe.");
  }
  back("/admin/cupones", active ? "Cupón activado." : "Cupón desactivado.");
}

// --- Pruebas gratis ---------------------------------------------------------
export async function allowTrialAgainAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const rows = await sql<{ email_normalized: string }[]>`
    DELETE FROM lotbot.trials WHERE id = ${num(form.get("id"))} RETURNING email_normalized
  `;
  if (rows.length) await logEvent("Prueba gratis permitida otra vez", rows[0].email_normalized, "admin");
  back("/admin/pruebas", "Ese email (y ese ordenador) pueden volver a pedir la prueba.");
}

// --- Planes -----------------------------------------------------------------
export async function savePlanAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const id = num(form.get("id"));
  const name = cleanText(form.get("name"), 80);
  const slug = cleanText(form.get("slug"), 40).toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/-+/g, "-");
  const price = num(form.get("price"));
  if (!name || !slug || price == null || price < 0) back("/admin/planes", "⚠ Nombre, identificador y precio son obligatorios.");
  const durationRaw = num(form.get("duration_days"));
  const values = {
    slug,
    name,
    description: cleanText(form.get("description"), 300),
    price_cents: Math.round((price as number) * 100),
    currency: cleanText(form.get("currency"), 3).toUpperCase() || "EUR",
    period_label: cleanText(form.get("period_label"), 30) || "mes",
    duration_days: durationRaw && durationRaw > 0 ? Math.round(durationRaw) : null,
    max_devices: Math.max(1, Math.min(20, Math.round(num(form.get("max_devices"), 1) ?? 1))),
    features: sql.json(
      String(form.get("features") ?? "").split("\n").map((f) => f.trim()).filter(Boolean).slice(0, 20),
    ),
    billing_interval: ["month", "year"].includes(String(form.get("billing_interval"))) ? String(form.get("billing_interval")) : null,
    founder_price_cents: (() => {
      const founder = num(form.get("founder_price"));
      return founder != null && founder >= 0 ? Math.round(founder * 100) : null;
    })(),
    highlighted: form.get("highlighted") === "on",
    active: form.get("active") === "on",
    sort: Math.round(num(form.get("sort"), 0) ?? 0),
  };
  try {
    if (id) {
      await sql`UPDATE lotbot.plans SET ${sql(values)} WHERE id = ${id}`;
    } else {
      await sql`INSERT INTO lotbot.plans ${sql(values)}`;
    }
  } catch {
    back("/admin/planes", "⚠ Ya hay otro plan con ese identificador.");
  }
  await setSetting(null, "plans_are_examples", false);
  await logEvent(id ? "Plan modificado" : "Plan creado", `${name} · ${values.price_cents / 100} ${values.currency}`, "admin");
  back("/admin/planes", "Plan guardado.");
}

export async function deletePlanAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const id = num(form.get("id"));
  const used = await sql`SELECT 1 FROM lotbot.orders WHERE plan_id = ${id} LIMIT 1`;
  if (used.length) {
    await sql`UPDATE lotbot.plans SET active = false WHERE id = ${id}`;
    back("/admin/planes", "Ese plan tiene pedidos: se ha desactivado en vez de borrarlo.");
  }
  await sql`DELETE FROM lotbot.plans WHERE id = ${id}`;
  await logEvent("Plan borrado", String(id), "admin");
  back("/admin/planes", "Plan borrado.");
}

// --- Formas de pago ---------------------------------------------------------
export async function savePaymentMethodAction(form: FormData): Promise<void> {
  await requireAdmin();
  const sql = await db();
  const id = cleanText(form.get("id"), 40);
  await sql`
    UPDATE lotbot.payment_methods SET
      enabled = ${form.get("enabled") === "on"},
      name = ${cleanText(form.get("name"), 60) || id},
      instructions = ${String(form.get("instructions") ?? "").slice(0, 2000).trim()}
    WHERE id = ${id}
  `;
  await logEvent("Forma de pago guardada", id, "admin");
  back("/admin/pagos", "Forma de pago guardada.");
}

// --- Ajustes ----------------------------------------------------------------
export async function saveSettingsAction(form: FormData): Promise<void> {
  await requireAdmin();
  const current = await siteSettings();
  const hours = Math.round(num(form.get("trial_hours"), 24) ?? 24);
  await setSetting(null, "site", {
    ...current,
    brand: cleanText(form.get("brand"), 60) || "LOT Bot",
    whatsapp: cleanText(form.get("whatsapp"), 30),
    email: cleanEmail(form.get("email")) ?? "",
    legal_name: cleanText(form.get("legal_name"), 120),
    privacy_text: String(form.get("privacy_text") ?? "").slice(0, 8000).trim(),
    terms_text: String(form.get("terms_text") ?? "").slice(0, 12000).trim(),
    trial_hours: Math.max(1, Math.min(168, hours)),
    trial_enabled: form.get("trial_enabled") === "on",
  });
  await logEvent("Ajustes guardados", "", "admin");
  back("/admin/ajustes", "Ajustes guardados.");
}
