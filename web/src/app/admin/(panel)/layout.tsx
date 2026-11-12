import Link from "next/link";

import { requireAdmin } from "@/lib/auth";

import { logoutAction } from "../actions";

export const dynamic = "force-dynamic";
export const metadata = { robots: { index: false, follow: false } };

const LINKS = [
  ["/admin", "Resumen"],
  ["/admin/lanzamiento", "Lanzamiento"],
  ["/admin/suscripciones", "Suscripciones"],
  ["/admin/pedidos", "Pedidos"],
  ["/admin/licencias", "Licencias"],
  ["/admin/dispositivos", "Dispositivos"],
  ["/admin/versiones", "Versiones"],
  ["/admin/alertas", "Alertas"],
  ["/admin/pruebas", "Pruebas gratis"],
  ["/admin/clientes", "Clientes"],
  ["/admin/planes", "Planes y precios"],
  ["/admin/cupones", "Cupones"],
  ["/admin/pagos", "Formas de pago"],
  ["/admin/ajustes", "Ajustes"],
  ["/admin/seguridad", "Seguridad"],
  ["/admin/registro", "Registro"],
];

export default async function PanelLayout({ children }: { children: React.ReactNode }) {
  await requireAdmin();
  return (
    <div className="admin">
      <aside>
        <Link href="/admin" className="brand">
          <img src="/logo.svg" alt="" width={28} height={28} /> Admin
        </Link>
        <nav>
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href}>{label}</Link>
          ))}
          <Link href="/" target="_blank">Ver la web ↗</Link>
          <form action={logoutAction}>
            <button className="btn small" style={{ marginTop: 12 }}>Salir</button>
          </form>
        </nav>
      </aside>
      <main>{children}</main>
    </div>
  );
}
