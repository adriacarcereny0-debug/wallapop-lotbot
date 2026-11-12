"use client";

import Link from "next/link";
import { useState } from "react";

type Props = {
  plans: { slug: string; label: string }[];
  plan: string;
  methods: { id: string; name: string }[];
};

const HINTS: Record<string, string> = {
  tarjeta: "Pago seguro en la página de Stripe. Se renueva sola y la cancelas cuando quieras desde «Mi cuenta». Tu licencia se activa al momento.",
  bizum: "Te damos los datos y la referencia; activamos tu licencia al recibirlo.",
  transferencia: "Te damos la cuenta y la referencia; activamos tu licencia al recibirla.",
  paypal: "Te damos el enlace de PayPal; activamos tu licencia al recibirlo.",
};

export default function CheckoutForm({ plans, plan, methods }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [accountLink, setAccountLink] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan: form.get("plan"),
          method: form.get("method"),
          name: form.get("name"),
          email: form.get("email"),
          phone: form.get("phone"),
          accept: form.get("accept") === "on",
        }),
      });
      const data = await response.json();
      if (!data.ok) {
        setError(data.error || "No se ha podido crear el pedido.");
        setAccountLink(data.redirect || "");
        setBusy(false);
        return;
      }
      window.location.href = data.redirect;
    } catch {
      setError("No hay conexión. Inténtalo de nuevo.");
      setBusy(false);
    }
  }

  return (
    <form className="card stack" style={{ marginTop: 24 }} onSubmit={submit}>
      <label>
        Plan
        <select name="plan" defaultValue={plan}>
          {plans.map((p) => (
            <option key={p.slug} value={p.slug}>{p.label}</option>
          ))}
        </select>
      </label>
      <label>
        Nombre
        <input name="name" autoComplete="name" maxLength={120} required />
      </label>
      <label>
        Email (aquí recibirás tu licencia)
        <input name="email" type="email" autoComplete="email" maxLength={200} required />
      </label>
      <label>
        Teléfono (opcional)
        <input name="phone" type="tel" autoComplete="tel" maxLength={40} />
      </label>
      <div className="stack" style={{ gap: 8 }}>
        <span style={{ fontSize: 14, color: "var(--muted)" }}>Forma de pago</span>
        <div className="options">
          {methods.map((m, index) => (
            <label className="option" key={m.id}>
              <input type="radio" name="method" value={m.id} defaultChecked={index === 0} />
              <span>
                <b>{m.name}</b>
                <br />
                <span className="faint">{HINTS[m.id] ?? ""}</span>
              </span>
            </label>
          ))}
        </div>
      </div>
      <label className="check">
        <input type="checkbox" name="accept" required />
        <span>
          Acepto la <Link href="/privacidad">política de privacidad</Link>.
        </span>
      </label>
      {error && (
        <p className="error">
          {error} {accountLink && <Link href={accountLink}>Ir a Mi cuenta</Link>}
        </p>
      )}
      <button className="btn primary" disabled={busy}>{busy ? "Un momento…" : "Continuar con el pago"}</button>
    </form>
  );
}
