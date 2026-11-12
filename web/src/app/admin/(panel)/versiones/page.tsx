import { db } from "@/lib/db";
import type { Release } from "@/lib/releases";
import { formatDate } from "@/lib/util";

import { releaseUpdateAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

const PLATFORM_LABEL: Record<string, string> = {
  "windows-x64": "Windows",
  "mac-arm64": "Mac (chip Apple)",
  "mac-intel": "Mac (Intel)",
};

export default async function ReleasesPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const sql = await db();
  const rows = await sql<Release[]>`SELECT * FROM lotbot.releases ORDER BY version_sort DESC, platform LIMIT 300`;
  const devices = await sql<{ app_version: string; count: number }[]>`
    SELECT app_version, count(*)::int AS count FROM lotbot.devices
    WHERE status = 'activo' AND last_seen > now() - interval '14 days' AND app_version <> ''
    GROUP BY app_version ORDER BY app_version DESC
  `;
  return (
    <>
      <h1>Versiones</h1>
      <p className="muted">
        Cada versión la compila y la registra GitHub Actions al publicar una etiqueta <code>vX.Y.Z</code>. LOT Bot la
        descarga y la instala solo (solo con licencia activa). Aquí decides a cuántos llega (despliegue gradual), si
        es obligatoria o si la retiras. Retirar una versión hace que deje de ofrecerse; quien ya la tenga recibirá la
        siguiente buena.
      </p>
      <Flash ok={ok} />
      {devices.length > 0 && (
        <p className="faint">
          Ordenadores en uso (14 días) por versión: {devices.map((d) => `${d.app_version}: ${d.count}`).join(" · ")}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Versión</th><th>Plataforma</th><th>Canal</th><th>Estado</th><th>Llega a</th><th>Publicada</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><b>{r.version}</b>{r.mandatory && <><br /><span className="badge danger">Obligatoria</span></>}</td>
                <td>{PLATFORM_LABEL[r.platform] ?? r.platform}<br /><span className="faint">{(Number(r.size) / 1048576).toFixed(0)} MB</span></td>
                <td>{r.channel}</td>
                <td><span className={`badge ${r.status === "activa" ? "ok" : "off"}`}>{r.status}</span></td>
                <td>
                  <form action={releaseUpdateAction} className="row-actions">
                    <input type="hidden" name="id" value={r.id} />
                    <input type="hidden" name="op" value="rollout" />
                    <input name="rollout" defaultValue={r.rollout_percent} inputMode="numeric" style={{ width: 70, padding: "6px 8px" }} />
                    <span className="faint">%</span>
                    <button className="btn small">Guardar</button>
                  </form>
                </td>
                <td>{formatDate(r.created_at)}</td>
                <td>
                  <div className="row-actions">
                    <form action={releaseUpdateAction}>
                      <input type="hidden" name="id" value={r.id} />
                      <input type="hidden" name="op" value={r.status === "activa" ? "retire" : "restore"} />
                      <button className={`btn small${r.status === "activa" ? " danger" : ""}`}>{r.status === "activa" ? "Retirar" : "Volver a ofrecer"}</button>
                    </form>
                    <form action={releaseUpdateAction}>
                      <input type="hidden" name="id" value={r.id} />
                      <input type="hidden" name="op" value="mandatory" />
                      <button className="btn small">{r.mandatory ? "Quitar obligatoria" : "Hacer obligatoria"}</button>
                    </form>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={7} className="muted">Aún no hay versiones publicadas.</td></tr>}
          </tbody>
        </table>
      </div>
      {rows[0]?.notes && (
        <details className="card"><summary style={{ cursor: "pointer" }}>Notas de la {rows[0].version}</summary><div className="prose">{rows[0].notes}</div></details>
      )}
    </>
  );
}
