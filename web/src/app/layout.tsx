import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "LOT Bot · Publica en Wallapop sin repetir el trabajo", template: "%s · LOT Bot" },
  description:
    "LOT Bot publica tus anuncios de Wallapop en varias cuentas desde un único Anuncio principal. Prueba gratis 24 horas.",
};

export const viewport: Viewport = { themeColor: "#0b0c0f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
