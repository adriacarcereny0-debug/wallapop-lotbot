import Link from "next/link";

import { hasDatabase } from "@/lib/db";
import { listPlans, publicPaymentMethods, siteSettings, type PaymentMethod, type Plan } from "@/lib/store";
import { formatMoney } from "@/lib/util";

export const dynamic = "force-dynamic";

const FEATURES = [
  { icon: "✎", title: "Un anuncio, todas tus cuentas", text: "Escribes el Anuncio principal una vez (título, precio, fotos, categoría) y LOT Bot lo publica en las cuentas que elijas." },
  { icon: "⇉", title: "En cadena o a la vez", text: "Por turnos, o varias cuentas al mismo tiempo, cada una con su propio navegador, su sesión y su ritmo." },
  { icon: "◷", title: "A un ritmo prudente", text: "Intervalo mínimo entre anuncios, descansos por cuenta y más calma si Wallapop pide una verificación." },
  { icon: "▣", title: "Fotos que no se repiten", text: "Una foto distinta en cada anuncio. Si falta o está dañada, te avisa antes de publicar con menos fotos." },
  { icon: "!", title: "Tú completas la verificación", text: "Si Wallapop pide comprobar que eres tú, LOT Bot te avisa, la completas y sigue solo desde el mismo paso." },
  { icon: "⌫", title: "Controla y limpia", text: "Visitas y favoritos de cada anuncio, borrado en bloque y máximo de anuncios por cuenta." },
  { icon: "✦", title: "Asistente", text: "«Publica 6 anuncios en las cuentas 2 y 4»: pídeselo con tus palabras y confirma el plan." },
  { icon: "⌂", title: "Tus datos, en tu ordenador", text: "Cuentas, anuncios y fotos se quedan en tu equipo. Inicias sesión tú: LOT Bot no guarda tu contraseña." },
];

const STEPS = [
  { title: "Instala LOT Bot", text: "En Windows o Mac. Pruébalo primero en modo DEMO, sin publicar nada." },
  { title: "Conecta tus cuentas", text: "Inicias sesión en Wallapop en la ventana de cada cuenta." },
  { title: "Prepara el Anuncio principal", text: "Título, descripción, precio y tus fotos." },
  { title: "Publica", text: "Elige cuentas y cuántos anuncios. Sigues el progreso en directo." },
];

const FAQ = [
  { q: "¿Qué incluye la prueba gratis?", a: "Todo LOT Bot durante 24 horas, sin pagar nada. Es de un solo uso por persona y ordenador." },
  { q: "¿En qué ordenadores funciona?", a: "Windows 10/11 y Mac (chip Apple o Intel). Necesita Google Chrome o Microsoft Edge instalado." },
  { q: "¿LOT Bot resuelve los CAPTCHA?", a: "No. Si Wallapop pide una verificación, LOT Bot te avisa y la completas tú; después sigue solo." },
  { q: "¿Guarda mis contraseñas de Wallapop?", a: "No. Inicias sesión tú en la ventana de cada cuenta y la sesión se queda en tu ordenador." },
  { q: "¿Puedo cancelar?", a: "Los planes no tienen permanencia: si no renuevas, la licencia termina al acabar su periodo." },
];

async function loadData(): Promise<{ plans: Plan[]; methods: PaymentMethod[]; hours: number; trial: boolean }> {
  if (!hasDatabase()) return { plans: [], methods: [], hours: 24, trial: true };
  try {
    const [plans, methods, settings] = await Promise.all([listPlans(), publicPaymentMethods(), siteSettings()]);
    return { plans, methods, hours: settings.trial_hours, trial: settings.trial_enabled };
  } catch (error) {
    console.error("Portada:", error);
    return { plans: [], methods: [], hours: 24, trial: true };
  }
}

export default async function Home() {
  const { plans, methods, hours, trial } = await loadData();
  return (
    <>
      <section className="hero">
        <div className="wrap">
          <div className="eyebrow">Publicación automática para Wallapop</div>
          <h1>
            Publica más. <span>Trabaja menos.</span>
          </h1>
          <p className="lead">
            LOT Bot publica tus anuncios de Wallapop en todas tus cuentas a partir de un único Anuncio principal:
            sin copiar, pegar ni subir fotos una y otra vez.
          </p>
          <div className="actions">
            {trial && (
              <Link href="/prueba" className="btn primary">
                Probar gratis {hours} h
              </Link>
            )}
            <Link href="#precios" className="btn">
              Ver precios
            </Link>
          </div>
          <p className="note">Windows y Mac · Sin tarjeta para la prueba</p>
        </div>
      </section>

      <section id="funciones" className="alt">
        <div className="wrap">
          <h2 className="title">Todo lo que hace por ti</h2>
          <p className="sub">Pensado para quien vende el mismo producto en varias cuentas de Wallapop.</p>
          <div className="grid">
            {FEATURES.map((f) => (
              <div className="card" key={f.title}>
                <div className="icon" aria-hidden>{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <h2 className="title">Así funciona</h2>
          <p className="sub">En unos minutos tienes la primera cola en marcha.</p>
          <div className="steps">
            {STEPS.map((s) => (
              <div className="card step" key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="precios" className="alt">
        <div className="wrap">
          <h2 className="title">Precios</h2>
          <p className="sub">Sin permanencia. Elige el plan y la forma de pago que prefieras.</p>
          {plans.length ? (
            <div className="plans">
              {plans.map((plan) => (
                <div className={`card plan${plan.highlighted ? " featured" : ""}`} key={plan.id}>
                  {plan.highlighted && <span className="badge">El más elegido</span>}
                  <div>
                    <h3 style={{ margin: 0 }}>{plan.name}</h3>
                    {plan.description && <p>{plan.description}</p>}
                  </div>
                  <div className="price">
                    {formatMoney(plan.price_cents, plan.currency)} <small>/ {plan.period_label}</small>
                  </div>
                  <ul>
                    {plan.features.map((feature) => (
                      <li key={feature}>{feature}</li>
                    ))}
                  </ul>
                  <Link href={`/comprar?plan=${plan.slug}`} className={`btn${plan.highlighted ? " primary" : ""}`}>
                    Elegir {plan.name}
                  </Link>
                </div>
              ))}
            </div>
          ) : (
            <div className="card">
              <p>Los precios se publicarán muy pronto. Mientras tanto, prueba LOT Bot gratis.</p>
            </div>
          )}
          {methods.length > 0 && (
            <div className="methods">
              <span>Formas de pago:</span>
              {methods.map((m) => (
                <span className="chip" key={m.id}>{m.name}</span>
              ))}
            </div>
          )}
        </div>
      </section>

      {trial && (
        <section>
          <div className="wrap">
            <div className="trial">
              <div>
                <div className="eyebrow">Prueba gratis</div>
                <h2 className="title" style={{ marginTop: 8 }}>{hours} horas para probarlo todo</h2>
                <p className="muted" style={{ margin: 0 }}>
                  Sin tarjeta y sin compromiso. Un solo uso por persona: te damos tu clave al momento.
                </p>
              </div>
              <div style={{ textAlign: "center" }}>
                <Link href="/prueba" className="btn primary">
                  Empezar la prueba gratis
                </Link>
              </div>
            </div>
          </div>
        </section>
      )}

      <section className="faq">
        <div className="wrap" style={{ maxWidth: 820 }}>
          <h2 className="title">Preguntas frecuentes</h2>
          {FAQ.map((item) => (
            <details key={item.q}>
              <summary>{item.q}</summary>
              <p>{item.a}</p>
            </details>
          ))}
        </div>
      </section>
    </>
  );
}
