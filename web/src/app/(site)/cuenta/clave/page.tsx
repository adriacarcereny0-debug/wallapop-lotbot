import type { Metadata } from "next";
import Link from "next/link";

import { tokenCustomer } from "@/lib/customer-auth";

import { SetPasswordForm } from "../Forms";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Poner contraseña", robots: { index: false } };

export default async function SetPasswordPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token = "" } = await searchParams;
  const customer = await tokenCustomer(token);
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Mi cuenta</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0 8px" }}>Poner contraseña</h1>
        {customer ? (
          <>
            <p className="muted" style={{ marginTop: 0 }}>Cuenta: <b>{customer.email}</b></p>
            <SetPasswordForm token={token} />
          </>
        ) : (
          <div className="card stack">
            <p>Este enlace ha caducado o ya se ha usado.</p>
            <p className="faint">Escríbenos y te mandamos otro, o <Link href="/cuenta/entrar">entra</Link> si ya tienes contraseña.</p>
          </div>
        )}
      </div>
    </div>
  );
}
