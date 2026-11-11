import type { Metadata } from "next";

import { hasDatabase } from "@/lib/db";
import { siteSettings } from "@/lib/store";

import TrialForm from "./TrialForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Prueba gratis" };

export default async function TrialPage() {
  let hours = 24;
  let enabled = true;
  if (hasDatabase()) {
    try {
      const settings = await siteSettings();
      hours = settings.trial_hours;
      enabled = settings.trial_enabled;
    } catch {
      /* se muestra el formulario igualmente */
    }
  }
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Prueba gratis</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0" }}>
          Prueba LOT Bot {hours} horas gratis
        </h1>
        <p className="muted">
          Sin tarjeta. Es de un solo uso: una prueba por persona y por ordenador. Las {hours} horas empiezan a contar
          en cuanto pidas tu clave.
        </p>
        {enabled ? (
          <TrialForm hours={hours} />
        ) : (
          <div className="card">La prueba gratis no está disponible ahora mismo. Elige un plan o escríbenos.</div>
        )}
      </div>
    </div>
  );
}
