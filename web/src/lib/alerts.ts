/**
 * Señales de posible abuso de licencias (solo avisan; no bloquean nada solas).
 * Tú decides en /admin si suspender, desvincular o bloquear.
 */
import { db } from "./db";

export const RULES = {
  /** Conexiones distintas en 7 días por cada ordenador permitido. */
  connectionsPerSeat: 3,
  /** Activaciones + desvinculaciones en 30 días. */
  deviceChanges: 6,
  /** Claves inventadas desde una conexión en 24 h. */
  failedKeys: 10,
  /** Licencias distintas activadas en un mismo ordenador. */
  licensesPerDevice: 3,
};

export type Alert = {
  kind: "conexiones" | "cambios" | "claves" | "ordenador";
  title: string;
  detail: string;
  license_id: number | null;
  key: string | null;
  email: string | null;
};

export async function licenseAlerts(): Promise<Alert[]> {
  const sql = await db();
  const alerts: Alert[] = [];

  const shared = await sql<{ license_id: number; key: string; email: string | null; ips: number; seats: number }[]>`
    SELECT l.id AS license_id, l.key, c.email, count(DISTINCT x.ip_hash)::int AS ips, l.max_devices AS seats
    FROM lotbot.license_connections x
    JOIN lotbot.licenses l ON l.id = x.license_id
    LEFT JOIN lotbot.customers c ON c.id = l.customer_id
    WHERE x.day > current_date - 7 AND l.status = 'activa'
    GROUP BY l.id, c.email
    HAVING count(DISTINCT x.ip_hash) > ${RULES.connectionsPerSeat} * l.max_devices
    ORDER BY ips DESC LIMIT 100
  `;
  for (const r of shared) {
    alerts.push({
      kind: "conexiones", license_id: r.license_id, key: r.key, email: r.email,
      title: "Muchas conexiones distintas",
      detail: `${r.ips} conexiones distintas en 7 días para ${r.seats} ordenador${r.seats === 1 ? "" : "es"}. Puede ser una licencia compartida (o alguien que viaja o usa datos móviles).`,
    });
  }

  const changes = await sql<{ license_id: number; key: string; email: string | null; n: number }[]>`
    SELECT l.id AS license_id, l.key, c.email, count(*)::int AS n
    FROM lotbot.license_events e
    JOIN lotbot.licenses l ON l.id = e.license_id
    LEFT JOIN lotbot.customers c ON c.id = l.customer_id
    WHERE e.kind IN ('activacion', 'desvinculado_por_cliente') AND e.at > now() - interval '30 days'
    GROUP BY l.id, c.email
    HAVING count(*) > ${RULES.deviceChanges}
    ORDER BY n DESC LIMIT 100
  `;
  for (const r of changes) {
    alerts.push({
      kind: "cambios", license_id: r.license_id, key: r.key, email: r.email,
      title: "Cambia mucho de ordenador",
      detail: `${r.n} activaciones o desvinculaciones en 30 días.`,
    });
  }

  const guessing = await sql<{ ip_hash: string; n: number }[]>`
    SELECT ip_hash, count(*)::int AS n FROM lotbot.license_events
    WHERE kind = 'clave_inexistente' AND at > now() - interval '24 hours' AND ip_hash <> ''
    GROUP BY ip_hash HAVING count(*) >= ${RULES.failedKeys}
    ORDER BY n DESC LIMIT 50
  `;
  for (const r of guessing) {
    alerts.push({
      kind: "claves", license_id: null, key: null, email: null,
      title: "Prueban claves inventadas",
      detail: `${r.n} claves que no existen en 24 h desde una misma conexión (${r.ip_hash.slice(0, 8)}…). Se frena sola a partir de 20 por hora.`,
    });
  }

  const multi = await sql<{ fingerprint: string; n: number; keys: string[] }[]>`
    SELECT d.fingerprint, count(DISTINCT d.license_id)::int AS n, array_agg(DISTINCT l.key) AS keys
    FROM lotbot.devices d JOIN lotbot.licenses l ON l.id = d.license_id
    GROUP BY d.fingerprint HAVING count(DISTINCT d.license_id) >= ${RULES.licensesPerDevice}
    ORDER BY n DESC LIMIT 50
  `;
  for (const r of multi) {
    alerts.push({
      kind: "ordenador", license_id: null, key: null, email: null,
      title: "Un ordenador con muchas licencias",
      detail: `El ordenador ${r.fingerprint.slice(0, 10)}… ha usado ${r.n} licencias: ${r.keys.slice(0, 6).join(", ")}.`,
    });
  }
  return alerts;
}
