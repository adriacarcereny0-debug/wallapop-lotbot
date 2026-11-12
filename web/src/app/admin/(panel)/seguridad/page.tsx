import { pendingSecret, twoFactorEnabled } from "@/lib/totp";

import { twoFactorConfirmAction, twoFactorDisableAction, twoFactorStartAction } from "../../actions";
import Flash from "../Flash";

export const dynamic = "force-dynamic";

export default async function SecurityPage({ searchParams }: { searchParams: Promise<{ ok?: string }> }) {
  const { ok } = await searchParams;
  const enabled = await twoFactorEnabled();
  const pending = enabled ? null : await pendingSecret();
  const uri = pending ? `otpauth://totp/LOT%20Bot:admin?secret=${pending}&issuer=LOT%20Bot&digits=6&period=30` : "";
  return (
    <>
      <h1>Seguridad</h1>
      <p className="muted">
        Verificación en dos pasos: además de la contraseña, para entrar en /admin hará falta el código de 6 cifras
        que da una app del móvil (Google Authenticator, Microsoft Authenticator, Authy, 1Password…).
      </p>
      <Flash ok={ok} />
      <div className="card stack" style={{ maxWidth: 640 }}>
        {enabled ? (
          <>
            <p><span className="badge ok">Activada</span> Para entrar hace falta la contraseña y el código.</p>
            <form action={twoFactorDisableAction} className="toolbar">
              <label>Código actual para desactivarla<input name="code" inputMode="numeric" maxLength={6} required /></label>
              <button className="btn small danger">Desactivar</button>
            </form>
          </>
        ) : pending ? (
          <>
            <p><b>1.</b> En la app, «Añadir cuenta» → «Introducir clave» y escribe esta clave (tipo «basada en tiempo»):</p>
            <div className="keybox" style={{ fontSize: 18 }}>{pending.match(/.{1,4}/g)?.join(" ")}</div>
            <p className="faint">Desde el móvil también puedes abrir este enlace: <a href={uri}>añadir a la app</a>.</p>
            <p><b>2.</b> Escribe el código que te da la app para activarla:</p>
            <form action={twoFactorConfirmAction} className="toolbar">
              <label>Código<input name="code" inputMode="numeric" maxLength={6} required autoComplete="one-time-code" /></label>
              <button className="btn primary small">Activar</button>
            </form>
            <p className="faint">Guarda la clave en un sitio seguro: si pierdes el móvil la necesitarás.</p>
          </>
        ) : (
          <>
            <p><span className="badge off">Desactivada</span></p>
            <form action={twoFactorStartAction}><button className="btn primary small">Activar la verificación en dos pasos</button></form>
          </>
        )}
      </div>
    </>
  );
}
