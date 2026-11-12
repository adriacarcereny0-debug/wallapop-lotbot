"use server";

/**
 * Acciones del panel /admin. Todas comprueban primero la sesión.
 */
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { login, logout, requireAdmin } from "@/lib/auth";
import { db, logEvent, setSetting } from "@/lib/db";
import { issueLicense, markOrderPaid, siteSettings, upsertCustomer } from "@/lib/store";
import { cleanEmail, cleanText } from "@/lib/util";

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
  const result = await login(String(form.get("password") ?? ""));
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
    trial_hours: Math.max(1, Math.min(168, hours)),
    trial_enabled: form.get("trial_enabled") === "on",
  });
  await logEvent("Ajustes guardados", "", "admin");
  back("/admin/ajustes", "Ajustes guardados.");
}
