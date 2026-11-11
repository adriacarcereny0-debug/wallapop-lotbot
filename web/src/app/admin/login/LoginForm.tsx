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
      {state.error && <p className="error">{state.error}</p>}
      <button className="btn primary" disabled={pending}>{pending ? "Entrando…" : "Entrar"}</button>
    </form>
  );
}
