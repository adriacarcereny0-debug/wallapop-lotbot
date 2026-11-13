import { db } from "@/lib/db";
import { formatDate } from "@/lib/util";

export const dynamic = "force-dynamic";

const KINDS: Record<string, string> = {
  activacion: "Activación en un ordenador",
  activacion_rechazada: "Activación rechazada",
  desvinculado_por_cliente: "Ordenador desvinculado por el cliente",
  clave_inexistente: "Clave que no existe",
};

export default async function HistoryPage({ searchParams }: { searchParams: Promise<{ q?: string; tipo?: string }> }) {
  const { q = "", tipo = "" } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const rows = await sql<{ id: number; at: Date; kind: string; fingerprint: string; detail: string; key: string | null; email: string | null }[]>`
    SELECT e.id, e.at, e.kind, e.fingerprint, e.detail, l.key, c.email
    FROM lotbot.license_events e
    LEFT JOIN lotbot.licenses l ON l.id = e.license_id
    LEFT JOIN lotbot.customers c ON c.id = l.customer_id
    WHERE (${tipo} = '' OR e.kind = ${tipo})
      AND (${q.trim()} = '' OR lower(l.key) LIKE ${like} OR lower(c.email) LIKE ${like} OR lower(e.fingerprint) LIKE ${like})
    ORDER BY e.id DESC LIMIT 500
  `;
  return (
    <>
      <h1>Historial de activaciones</h1>
      <p className="muted">
        Activaciones, rechazos, cambios de ordenador y claves inventadas, por licencia (últimos 500). Las renovaciones
        normales cada pocas horas no se apuntan aquí: se ven en «Dispositivos» (último uso).
      </p>
      <form className="toolbar">
        <label>Qué
          <select name="tipo" defaultValue={tipo}>
            <option value="">Todo</option>
            {Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>Buscar<input name="q" defaultValue={q} placeholder="Clave, email u ordenador" /></label>
        <button className="btn small">Filtrar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fecha</th><th>Qué</th><th>Licencia</th><th>Ordenador</th><th>Detalle</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{formatDate(r.at)}</td>
                <td>{KINDS[r.kind] ?? r.kind}</td>
                <td>{r.key ? <><code>{r.key}</code>{r.email && <><br /><span className="faint">{r.email}</span></>}</> : "—"}</td>
                <td>{r.fingerprint ? <code>{r.fingerprint.slice(0, 12)}…</code> : "—"}</td>
                <td>{r.detail || "—"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="muted">Nada con ese filtro.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
