import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { adminConfigured, isAdmin } from "@/lib/auth";
import { hasDatabase } from "@/lib/db";

import LoginForm from "./LoginForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Acceso", robots: { index: false } };

export default async function LoginPage() {
  if (await isAdmin()) redirect("/admin");
  const problems = [
    !hasDatabase() && "Falta la base de datos (DATABASE_URL). En Vercel: Storage → Neon → conectar al proyecto.",
    !adminConfigured() && "Falta ADMIN_PASSWORD (mínimo 8 caracteres) en Settings → Environment Variables.",
  ].filter(Boolean) as string[];
  return (
    <div className="form-page">
      <div className="wrap panel" style={{ maxWidth: 420 }}>
        <div className="brand" style={{ marginBottom: 24 }}>
          <img src="/logo.svg" alt="" width={34} height={34} /> LOT Bot · Admin
        </div>
        {problems.map((p) => (
          <div className="notice" key={p}>{p}</div>
        ))}
        {problems.length === 0 && <LoginForm />}
      </div>
    </div>
  );
}
