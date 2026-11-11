"use client";

import Link from "next/link";
import { useState } from "react";

type Result = { ok: true; key: string; expiresAt: string; hours: number } | { ok: false; error: string };

export default function TrialForm({ hours }: { hours: number }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [copied, setCopied] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setResult(null);
    try {
      const response = await fetch("/api/trial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          phone: form.get("phone"),
          website: form.get("website"),
          accept: form.get("accept") === "on",
        }),
      });
      setResult(await response.json());
    } catch {
      setResult({ ok: false, error: "No hay conexión. Inténtalo de nuevo." });
    } finally {
      setBusy(false);
    }
  }

  if (result?.ok) {
    const until = new Intl.DateTimeFormat("es-ES", { dateStyle: "full", timeStyle: "short" }).format(
      new Date(result.expiresAt),
    );
    return (
      <div className="card stack" style={{ marginTop: 24 }}>
        <h2 style={{ margin: 0 }} className="success">¡Tu prueba está activada!</h2>
        <p className="muted" style={{ margin: 0 }}>Esta es tu clave. Guárdala: solo se muestra una vez.</p>
        <div className="keybox">{result.key}</div>
        <button
          type="button"
          className="btn"
          onClick={() => navigator.clipboard?.writeText(result.key).then(() => setCopied(true))}
        >
          {copied ? "Copiada" : "Copiar clave"}
        </button>
        <p className="faint" style={{ margin: 0 }}>Válida hasta el {until}.</p>
        <p className="muted" style={{ margin: 0 }}>
          Te ayudamos a instalar LOT Bot y a conectar tus cuentas. Cuando acaben las {hours} horas, elige un plan para
          seguir.
        </p>
        <Link href="/#precios" className="btn primary">Ver planes</Link>
      </div>
    );
  }

  return (
    <form className="card stack" style={{ marginTop: 24 }} onSubmit={submit}>
      <label>
        Nombre
        <input name="name" autoComplete="name" maxLength={120} />
      </label>
      <label>
        Email
        <input name="email" type="email" required autoComplete="email" maxLength={200} />
      </label>
      <label>
        Teléfono (opcional, para ayudarte por WhatsApp)
        <input name="phone" type="tel" autoComplete="tel" maxLength={40} />
      </label>
      <div className="honey" aria-hidden>
        <label>
          No rellenes este campo
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" name="accept" required />
        <span>
          Acepto la <Link href="/privacidad">política de privacidad</Link>.
        </span>
      </label>
      {result && !result.ok && <p className="error">{result.error}</p>}
      <button className="btn primary" disabled={busy}>
        {busy ? "Activando…" : `Activar mi prueba de ${hours} h`}
      </button>
    </form>
  );
}
