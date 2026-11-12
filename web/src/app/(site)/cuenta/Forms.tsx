"use client";

import Link from "next/link";
import { useActionState } from "react";

import {
  changePasswordAction,
  loginAction,
  registerAction,
  setPasswordAction,
  type AccountFormState,
} from "./actions";

function Message({ state }: { state: AccountFormState }) {
  if (state.error) return <p className="error" role="alert">{state.error}</p>;
  if (state.ok) return <p className="success">{state.ok}</p>;
  return null;
}

export function LoginForm({ next }: { next?: string }) {
  const [state, action, pending] = useActionState(loginAction, {});
  return (
    <form action={action} className="card stack">
      <input type="hidden" name="next" value={next ?? "/cuenta"} />
      <label>Email<input name="email" type="email" autoComplete="email" required maxLength={200} defaultValue={state.values?.email} /></label>
      <label>Contraseña<input name="password" type="password" autoComplete="current-password" required maxLength={200} /></label>
      <Message state={state} />
      <button className="btn primary" disabled={pending}>{pending ? "Entrando…" : "Entrar"}</button>
      <p className="faint">
        ¿No tienes cuenta? <Link href="/cuenta/registro">Créala</Link>. ¿Has olvidado la contraseña? Escríbenos y
        te enviamos un enlace para poner otra.
      </p>
    </form>
  );
}

export function RegisterForm({ email }: { email?: string }) {
  const [state, action, pending] = useActionState(registerAction, {});
  return (
    <form action={action} className="card stack">
      <label>Nombre<input name="name" autoComplete="name" maxLength={120} defaultValue={state.values?.name} /></label>
      <label>Email<input name="email" type="email" autoComplete="email" required maxLength={200} defaultValue={state.values?.email ?? email} /></label>
      <label>
        Contraseña (mínimo 10 caracteres)
        <input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={200} />
      </label>
      <label>Repite la contraseña<input name="password2" type="password" autoComplete="new-password" required maxLength={200} /></label>
      <label>
        Clave de licencia {state.needsKey ? "" : "(solo si ya eres cliente)"}
        <input name="license_key" placeholder="LOTB-XXXX-XXXX-XXXX" maxLength={40} required={state.needsKey}
          defaultValue={state.values?.license_key}
          style={{ fontFamily: "ui-monospace, monospace" }} />
      </label>
      <label className="check">
        <input type="checkbox" name="accept" required defaultChecked={state.values?.accept === "on"} />
        <span>Acepto los <Link href="/terminos">términos de uso</Link> y la <Link href="/privacidad">política de privacidad</Link>.</span>
      </label>
      <Message state={state} />
      <button className="btn primary" disabled={pending}>{pending ? "Creando…" : "Crear mi cuenta"}</button>
      <p className="faint">¿Ya tienes cuenta? <Link href="/cuenta/entrar">Entra</Link>.</p>
    </form>
  );
}

export function SetPasswordForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(setPasswordAction, {});
  return (
    <form action={action} className="card stack">
      <input type="hidden" name="token" value={token} />
      <label>
        Contraseña nueva (mínimo 10 caracteres)
        <input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={200} />
      </label>
      <label>Repite la contraseña<input name="password2" type="password" autoComplete="new-password" required maxLength={200} /></label>
      <Message state={state} />
      <button className="btn primary" disabled={pending}>{pending ? "Guardando…" : "Guardar contraseña"}</button>
    </form>
  );
}

export function ChangePasswordForm() {
  const [state, action, pending] = useActionState(changePasswordAction, {});
  return (
    <form action={action} className="stack">
      <label>Contraseña actual<input name="current" type="password" autoComplete="current-password" required maxLength={200} /></label>
      <label>
        Contraseña nueva (mínimo 10 caracteres)
        <input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={200} />
      </label>
      <label>Repite la nueva<input name="password2" type="password" autoComplete="new-password" required maxLength={200} /></label>
      <Message state={state} />
      <button className="btn small" disabled={pending}>{pending ? "Guardando…" : "Cambiar contraseña"}</button>
    </form>
  );
}
