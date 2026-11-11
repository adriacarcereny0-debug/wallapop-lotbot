import type { Metadata } from "next";

import { hasDatabase } from "@/lib/db";
import { DEFAULT_SETTINGS, siteSettings } from "@/lib/store";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Privacidad" };

export default async function PrivacyPage() {
  const settings = hasDatabase() ? await siteSettings().catch(() => DEFAULT_SETTINGS) : DEFAULT_SETTINGS;
  const owner = settings.legal_name || settings.brand;
  return (
    <div className="form-page">
      <div className="wrap panel">
        <h1 className="title">Política de privacidad</h1>
        {settings.privacy_text ? (
          <div className="prose">{settings.privacy_text}</div>
        ) : (
          <div className="prose">
            {`Responsable: ${owner}${settings.email ? ` (${settings.email})` : ""}.

Qué datos pedimos: nombre, email y, si quieres, teléfono, para darte tu prueba gratis o tu licencia, ayudarte a instalar LOT Bot y atender tus pagos. De la conexión solo guardamos una huella irreversible para evitar abusos de la prueba gratis.

Pagos con tarjeta: los gestiona Stripe en su propia página; nunca vemos ni guardamos los datos de tu tarjeta.

No vendemos ni cedemos tus datos. Puedes pedir verlos, corregirlos o borrarlos escribiéndonos.`}
          </div>
        )}
      </div>
    </div>
  );
}
