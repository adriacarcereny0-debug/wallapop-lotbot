import type { Metadata } from "next";

import { hasDatabase } from "@/lib/db";
import { DEFAULT_SETTINGS, siteSettings } from "@/lib/store";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Términos de uso y licencia" };

export default async function TermsPage() {
  const settings = hasDatabase() ? await siteSettings().catch(() => DEFAULT_SETTINGS) : DEFAULT_SETTINGS;
  const owner = settings.legal_name || settings.brand;
  return (
    <div className="form-page">
      <div className="wrap panel">
        <h1 className="title">Términos de uso y licencia</h1>
        {settings.terms_text ? (
          <div className="prose">{settings.terms_text}</div>
        ) : (
          <div className="prose">
            {`Titular: ${owner}${settings.email ? ` (${settings.email})` : ""}.

Licencia: al contratar LOT Bot recibes una licencia de uso personal e intransferible para el número de ordenadores de tu plan (mensual: 1; anual: 2). No se puede compartir, revender, copiar ni modificar el programa.

Suscripción: se renueva sola al final de cada periodo. Puedes cancelarla cuando quieras desde «Mi cuenta»; seguirá funcionando hasta el final del periodo ya pagado. Si un cobro falla, LOT Bot sigue funcionando unos días de margen mientras se reintenta el pago; después la licencia se suspende hasta que se pague.

Prueba gratis: de un solo uso por persona y ordenador.

Uso responsable: LOT Bot no está afiliado a Wallapop. Eres responsable de cumplir las normas de Wallapop en tus cuentas. LOT Bot nunca intenta saltarse sus verificaciones: cuando Wallapop pide una, la completas tú.

Tus datos se quedan en tu ordenador y no se borran al caducar la licencia.

Ver también la política de privacidad.`}
          </div>
        )}
      </div>
    </div>
  );
}
