import { db } from "@/lib/db";
import { formatDate } from "@/lib/util";

export const dynamic = "force-dynamic";

export default async function LogPage({ searchParams }: { searchParams: Promise<{ quien?: string; q?: string }> }) {
  const { quien = "", q = "" } = await searchParams;
  const sql = await db();
  const like = `%${q.trim().toLowerCase()}%`;
  const events = await sql<{ id: number; at: Date; actor: string; action: string; detail: string }[]>`
    SELECT * FROM lotbot.events
    WHERE (${quien} = '' OR actor = ${quien})
      AND (${q.trim()} = '' OR lower(action) LIKE ${like} OR lower(detail) LIKE ${like})
    ORDER BY id DESC LIMIT 500
  `;
  const actors = await sql<{ actor: string; n: number }[]>`
    SELECT actor, count(*)::int AS n FROM lotbot.events GROUP BY actor ORDER BY n DESC
  `;
  return (
    <>
      <h1>Registro</h1>
      <p className="muted">
        Todo lo que ha pasado en la web y en el panel (últimos 500 que cumplen el filtro). «admin» = lo que se ha
        hecho desde este panel.
      </p>
      <form className="toolbar">
        <label>Quién
          <select name="quien" defaultValue={quien}>
            <option value="">Todos</option>
            {actors.map((a) => <option key={a.actor} value={a.actor}>{a.actor} ({a.n})</option>)}
          </select>
        </label>
        <label>Buscar<input name="q" defaultValue={q} placeholder="Acción o detalle" /></label>
        <button className="btn small">Filtrar</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fecha</th><th>Quién</th><th>Qué</th><th>Detalle</th></tr></thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}><td>{formatDate(e.at)}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.detail}</td></tr>
            ))}
            {events.length === 0 && <tr><td colSpan={4} className="muted">Nada con ese filtro.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
