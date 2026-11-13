import { db } from "@/lib/db";
import { listPlans } from "@/lib/store";
import { formatDate } from "@/lib/util";

import {
  createLicenseAction,
  extendLicenseAction,
  resetDevicesAction,
  setLicenseStatusAction,
} from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = {
  id: number; key: string; kind: string; status: string; expires_at: Date | null; max_devices: number;
  notes: string; status_reason: string; created_at: Date; email: string | null; name: string | null; plan_name: string | null;
  devices: number; last_seen: Date | null;
};

export default async function LicensesPage({ searchParams }: { searchParams: Promise<{ q?: string; tipo?: string; estado?: string; ok?: string }> }) {
  const { q = "", tipo = "", estado = "", ok } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<Row[]>`
    SELECT l.*, c.email, c.name, p.name AS plan_name,
      (SELECT count(*)::int FROM lotbot.devices d WHERE d.license_id = l.id AND d.status = 'activo') AS devices,
      (SELECT max(last_seen) FROM lotbot.devices d WHERE d.license_id = l.id) AS last_seen
    FROM lotbot.licenses l
    LEFT JOIN lotbot.customers c ON c.id = l.customer_id
    LEFT JOIN lotbot.plans p ON p.id = l.plan_id
    WHERE (${tipo} = '' OR l.kind = ${tipo})
      AND (${estado} = ''
        OR (${estado} = 'activa' AND l.status = 'activa' AND (l.expires_at IS NULL OR l.expires_at > now()))
        OR (${estado} = 'caducada' AND l.status = 'activa' AND l.expires_at <= now())
        OR (${estado} IN ('suspendida', 'revocada') AND l.status = ${estado}))
      AND (${q.trim()} = '' OR lower(l.key) LIKE ${like} OR lower(c.email) LIKE ${like} OR lower(c.name) LIKE ${like})
    ORDER BY l.id DESC LIMIT 300
  `;
  const plans = await listPlans(false);
  const now = new Date();
  return (
    <>
      <h1>Licencias</h1>
      <p className="muted">Claves de LOT Bot: de pago, de prueba y las que regales o vendas a mano.</p>
      <Flash ok={ok} />
      <details className="card" style={{ margin: "16px 0" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>+ Crear una licencia a mano</summary>
        <form action={createLicenseAction} className="stack" style={{ marginTop: 16 }}>
          <div className="two">
            <label>Email del cliente<input name="email" type="email" required /></label>
            <label>Nombre<input name="name" /></label>
            <label>Teléfono<input name="phone" /></label>
            <label>Plan
              <select name="plan_id" defaultValue="">
                <option value="">Sin plan</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label>Días (vacío = los del plan; sin plan = sin caducidad)<input name="days" inputMode="numeric" /></label>
            <label>Ordenadores<input name="max_devices" inputMode="numeric" placeholder="1" /></label>
          </div>
          <label>Nota<input name="notes" placeholder="p. ej. pagado en mano" /></label>
          <button className="btn primary">Crear licencia</button>
        </form>
      </details>
      <form className="toolbar">
        <label>Tipo
          <select name="tipo" defaultValue={tipo}>
            <option value="">Todas</option><option value="pago">De pago</option>
            <option value="prueba">Prueba</option><option value="manual">Manual</option>
          </select>
        </label>
        <label>Estado
          <select name="estado" defaultValue={estado}>
            <option value="">Todos</option><option value="activa">Activas</option>
            <option value="caducada">Caducadas</option><option value="suspendida">Suspendidas</option>
            <option value="revocada">Revocadas</option>
          </select>
        </label>
        <label>Buscar<input name="q" defaultValue={q} placeholder="Clave, email o nombre" /></label>
        <button className="btn small">Filtrar</button>
      </form>
      <p className="faint">{rows.length} licencia{rows.length === 1 ? "" : "s"}{rows.length === 300 ? " (las 300 más recientes)" : ""}. <a href={`/admin/historial?q=${encodeURIComponent(q)}`}>Ver historial de activaciones</a></p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Clave</th><th>Cliente</th><th>Tipo</th><th>Caduca</th><th>Estado</th><th>Ordenadores</th><th>Acciones</th></tr>
          </thead>
          <tbody>
            {rows.map((l) => {
              const expired = l.expires_at && new Date(l.expires_at) < now;
              return (
                <tr key={l.id}>
                  <td><code>{l.key}</code>{l.notes && <><br /><span className="faint">{l.notes}</span></>}</td>
                  <td>{l.name}<br /><span className="faint">{l.email}</span></td>
                  <td>{l.kind}{l.plan_name ? ` · ${l.plan_name}` : ""}</td>
                  <td>{l.expires_at ? formatDate(l.expires_at) : "Nunca"}</td>
                  <td>
                    <span className={`badge ${l.status !== "activa" ? "danger" : expired ? "off" : "ok"}`}>
                      {l.status !== "activa" ? l.status : expired ? "caducada" : "activa"}
                    </span>
                    {l.status_reason && <><br /><span className="faint">{l.status_reason}</span></>}
                  </td>
                  <td>{l.devices}/{l.max_devices}{l.last_seen && <><br /><span className="faint">visto {formatDate(l.last_seen)}</span></>}</td>
                  <td>
                    <div className="row-actions">
                      <form action={extendLicenseAction} style={{ display: "flex", gap: 6 }}>
                        <input type="hidden" name="id" value={l.id} />
                        <input name="days" defaultValue="30" inputMode="numeric" style={{ width: 64, padding: "6px 8px" }} aria-label="Días" />
                        <button className="btn small">+ días</button>
                      </form>
                      {l.status === "activa" ? (
                        <>
                          <form action={setLicenseStatusAction} style={{ display: "flex", gap: 6 }}>
                            <input type="hidden" name="id" value={l.id} />
                            <input type="hidden" name="status" value="suspendida" />
                            <input name="reason" placeholder="Motivo" style={{ width: 120, padding: "6px 8px" }} aria-label="Motivo de la suspensión" />
                            <button className="btn small danger">Suspender</button>
                          </form>
                          <form action={setLicenseStatusAction}>
                            <input type="hidden" name="id" value={l.id} />
                            <input type="hidden" name="status" value="revocada" />
                            <button className="btn small danger" title="Definitiva">Revocar</button>
                          </form>
                        </>
                      ) : (
                        <form action={setLicenseStatusAction}>
                          <input type="hidden" name="id" value={l.id} />
                          <input type="hidden" name="status" value="activa" />
                          <button className="btn small">Reactivar</button>
                        </form>
                      )}
                      {l.devices > 0 && (
                        <form action={resetDevicesAction}>
                          <input type="hidden" name="id" value={l.id} />
                          <button className="btn small" title="Para cambiar de ordenador">Desvincular ordenadores</button>
                        </form>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={7} className="muted">No hay licencias.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
