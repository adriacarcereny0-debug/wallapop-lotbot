"use client";

import { useActionState } from "react";

import { loginAction, type FormState } from "../actions";

export default function LoginForm() {
  const [state, action, pending] = useActionState<FormState, FormData>(loginAction, {});
  return (
    <form action={action} className="card stack">
      <label>
        Contraseña
        <input type="password" name="password" required autoFocus autoComplete="current-password" />
      </label>
      <label>
        Código de verificación <span className="faint">(si la tienes activada)</span>
        <input name="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" placeholder="123456" />
      </label>
      {state.error && <p className="error">{state.error}</p>}
      <button className="btn primary" disabled={pending}>{pending ? "Entrando…" : "Entrar"}</button>
    </form>
  );
}
