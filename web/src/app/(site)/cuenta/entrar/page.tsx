import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { accountsConfigured, currentCustomer } from "@/lib/customer-auth";

import { LoginForm } from "../Forms";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Entrar · Mi cuenta", robots: { index: false } };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  if (await currentCustomer()) redirect("/cuenta");
  const { next } = await searchParams;
  return (
    <div className="form-page">
      <div className="wrap panel">
        <div className="eyebrow">Mi cuenta</div>
        <h1 className="title" style={{ fontSize: 38, letterSpacing: "-0.03em", margin: "8px 0 20px" }}>Entrar</h1>
        {accountsConfigured() ? (
          <LoginForm next={next} />
        ) : (
          <div className="card">Las cuentas de cliente no están disponibles todavía.</div>
        )}
      </div>
    </div>
  );
}
