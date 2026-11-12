import Link from "next/link";

import { licenseAlerts, RULES } from "@/lib/alerts";

export const dynamic = "force-dynamic";

export default async function AlertsPage() {
  const alerts = await licenseAlerts();
  return (
    <>
      <h1>Alertas</h1>
      <p className="muted">
        Señales de posible abuso de licencias. Solo avisan: tú decides si suspender la licencia o desvincular o
        bloquear un ordenador. De las conexiones solo se guarda una huella irreversible, nunca la IP.
      </p>
      <p className="faint">
        Reglas: más de {RULES.connectionsPerSeat} conexiones distintas por ordenador permitido en 7 días · más de{" "}
        {RULES.deviceChanges} cambios de ordenador en 30 días · {RULES.failedKeys}+ claves inventadas en 24 h desde una
        conexión · un ordenador con {RULES.licensesPerDevice}+ licencias.
      </p>
      {alerts.length === 0 ? (
        <div className="notice ok">Sin alertas. Todo normal.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Alerta</th><th>Detalle</th><th>Licencia</th></tr></thead>
            <tbody>
              {alerts.map((a, i) => (
                <tr key={i}>
                  <td><span className="badge danger">{a.title}</span></td>
                  <td>{a.detail}</td>
                  <td>
                    {a.key ? (
                      <>
                        <code>{a.key}</code>
                        {a.email && <><br /><span className="faint">{a.email}</span></>}
                        <br />
                        <Link href={`/admin/dispositivos?q=${encodeURIComponent(a.key)}`}>Ver ordenadores</Link>
                      </>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
