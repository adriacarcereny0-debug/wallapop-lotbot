import { siteSettings } from "@/lib/store";

import { saveSettingsAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const s = await siteSettings();
  return (
    <>
      <h1>Ajustes</h1>
      <Flash ok={ok} />
      <form action={saveSettingsAction} className="card stack" style={{ marginTop: 16 }}>
        <h2 style={{ margin: 0 }}>Web y contacto</h2>
        <div className="two">
          <label>Nombre de la marca<input name="brand" defaultValue={s.brand} /></label>
          <label>Tu nombre o empresa (titular)<input name="legal_name" defaultValue={s.legal_name} /></label>
          <label>Email de contacto<input name="email" type="email" defaultValue={s.email} /></label>
          <label>WhatsApp (con prefijo, p. ej. 34600000000)<input name="whatsapp" defaultValue={s.whatsapp} /></label>
        </div>
        <h2 style={{ margin: "10px 0 0" }}>Prueba gratis</h2>
        <div className="toolbar" style={{ margin: 0 }}>
          <label className="check"><input type="checkbox" name="trial_enabled" defaultChecked={s.trial_enabled} /> Ofrecer la prueba gratis</label>
          <label>Duración (horas)<input name="trial_hours" inputMode="numeric" defaultValue={s.trial_hours} /></label>
        </div>
        <h2 style={{ margin: "10px 0 0" }}>Política de privacidad</h2>
        <label>
          Texto propio (vacío = se usa uno básico con tus datos)
          <textarea name="privacy_text" defaultValue={s.privacy_text} style={{ minHeight: 180 }} />
        </label>
        <div><button className="btn primary">Guardar ajustes</button></div>
      </form>
    </>
  );
}
