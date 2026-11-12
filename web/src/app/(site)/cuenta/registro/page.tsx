import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { accountsConfigured, currentCustomer } from "@/lib/customer-auth";

import { RegisterForm } from "../Forms";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Crear cuenta", robots: { index: false } };

export default async function RegisterPage({ searchParams }: { searchParams: Promise<{ email?: string }> }) {
  if (await currentCustomer()) redirect("/cuenta");
  const { email } = await searchParams;
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Mi cuenta</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0 8px" }}>Crear cuenta</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Desde tu cuenta ves tu licencia y tus ordenadores, te suscribes y gestionas el pago.
          Si ya usas LOT Bot, escribe tu clave de licencia y la vinculamos.
        </p>
        {accountsConfigured() ? <RegisterForm email={email} /> : <div className="card">Las cuentas de cliente no están disponibles todavía.</div>}
      </div>
    </div>
  );
}
