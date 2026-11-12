import { db } from "@/lib/db";
import { formatDate } from "@/lib/util";

export const dynamic = "force-dynamic";

export default async function LogPage() {
  const sql = await db();
  const events = await sql<{ id: number; at: Date; actor: string; action: string; detail: string }[]>`
    SELECT * FROM lotbot.events ORDER BY id DESC LIMIT 500
  `;
  return (
    <>
      <h1>Registro</h1>
      <p className="muted">Todo lo que ha pasado en la web y en el panel (últimos 500).</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fecha</th><th>Quién</th><th>Qué</th><th>Detalle</th></tr></thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}><td>{formatDate(e.at)}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.detail}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
