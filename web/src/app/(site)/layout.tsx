import Link from "next/link";

import { hasDatabase } from "@/lib/db";
import { DEFAULT_SETTINGS, siteSettings, type SiteSettings } from "@/lib/store";

export const dynamic = "force-dynamic";

async function settingsOrDefault(): Promise<SiteSettings> {
  if (!hasDatabase()) return DEFAULT_SETTINGS;
  try {
    return await siteSettings();
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  const settings = await settingsOrDefault();
  const whatsapp = settings.whatsapp.replace(/[^\d]/g, "");
  return (
    <>
      <header className="header">
        <div className="wrap">
          <Link href="/" className="brand">
            <img src="/logo.svg" alt="" width={30} height={30} />
            {settings.brand}
          </Link>
          <nav className="nav">
            <Link href="/#funciones" className="hide-sm">Funciones</Link>
            <Link href="/#precios">Precios</Link>
            <Link href="/prueba" className="btn primary small">Prueba gratis</Link>
          </nav>
        </div>
      </header>
      <main>{children}</main>
      <footer className="footer">
        <div className="wrap">
          <span>© {new Date().getFullYear()} {settings.legal_name || settings.brand}</span>
          {settings.email && <a href={`mailto:${settings.email}`}>{settings.email}</a>}
          {whatsapp && <a href={`https://wa.me/${whatsapp}`}>WhatsApp</a>}
          <Link href="/privacidad">Privacidad</Link>
          <span>LOT Bot no está afiliado a Wallapop.</span>
        </div>
      </footer>
    </>
  );
}
