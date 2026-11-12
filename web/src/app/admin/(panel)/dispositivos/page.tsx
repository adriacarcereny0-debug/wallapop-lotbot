import { db } from "@/lib/db";
import { formatDate } from "@/lib/util";

import { setDeviceStatusAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

type Row = {
  id: number; fingerprint: string; name: string; os: string; app_version: string; status: string;
  first_seen: Date; last_seen: Date; key: string; kind: string; email: string | null; ips: number;
};

export default async function DevicesPage({ searchParams }: { searchParams: Promise<{ q?: string; estado?: string; ok?: string }> }) {
  const { q = "", estado = "", ok } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<Row[]>`
    SELECT d.*, l.key, l.kind, c.email,
      (SELECT count(DISTINCT e.ip_hash)::int FROM lotbot.license_events e
        WHERE e.license_id = d.license_id AND e.at > now() - interval '7 days' AND e.ip_hash <> '') AS ips
    FROM lotbot.devices d
    JOIN lotbot.licenses l ON l.id = d.license_id
    LEFT JOIN lotbot.customers c ON c.id = l.customer_id
    WHERE (${estado} = '' OR d.status = ${estado})
      AND (${q.trim()} = '' OR lower(l.key) LIKE ${like} OR lower(c.email) LIKE ${like}
           OR lower(d.name) LIKE ${like} OR lower(d.fingerprint) LIKE ${like})
    ORDER BY d.last_seen DESC LIMIT 300
  `;
  return (
    <>
      <h1>Dispositivos</h1>
      <p className="muted">
        Ordenadores donde está activado LOT Bot. «Desvincular» libera la plaza (puede volver a activarse); «Bloquear»
        impide que ese ordenador use esa licencia. Varias conexiones distintas en pocos días pueden indicar una
        licencia compartida.
      </p>
      <Flash ok={ok} />
      <form className="toolbar">
        <label>Estado
          <select name="estado" defaultValue={estado}>
            <option value="">Todos</option><option value="activo">Activos</option>
            <option value="desvinculado">Desvinculados</option><option value="bloqueado">Bloqueados</option>
          </select>
        </label>
        <label>Buscar<input name="q" defaultValue={q} placeholder="Clave, email u ordenador" /></label>
        <button className="btn small">Filtrar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Ordenador</th><th>Licencia</th><th>Versión</th><th>Visto</th><th>Conexiones (7 días)</th><th>Estado</th><th>Acciones</th></tr></thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <td>{d.name || "Sin nombre"}<br /><span className="faint">{d.os} · <code>{d.fingerprint.slice(0, 12)}…</code></span></td>
                <td><code>{d.key}</code><br /><span className="faint">{d.kind} · {d.email}</span></td>
                <td>{d.app_version || "—"}</td>
                <td>{formatDate(d.last_seen)}<br /><span className="faint">desde {formatDate(d.first_seen)}</span></td>
                <td>{d.ips > 3 ? <span className="badge danger">{d.ips}</span> : d.ips}</td>
                <td><span className={`badge ${d.status === "activo" ? "ok" : d.status === "bloqueado" ? "danger" : "off"}`}>{d.status}</span></td>
                <td>
                  <div className="row-actions">
                    {d.status === "activo" && (
                      <form action={setDeviceStatusAction}><input type="hidden" name="id" value={d.id} /><input type="hidden" name="status" value="desvinculado" /><button className="btn small">Desvincular</button></form>
                    )}
                    {d.status !== "bloqueado" ? (
                      <form action={setDeviceStatusAction}><input type="hidden" name="id" value={d.id} /><input type="hidden" name="status" value="bloqueado" /><button className="btn small danger">Bloquear</button></form>
                    ) : (
                      <form action={setDeviceStatusAction}><input type="hidden" name="id" value={d.id} /><input type="hidden" name="status" value="desvinculado" /><button className="btn small">Desbloquear</button></form>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={7} className="muted">Todavía no hay ordenadores activados.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
