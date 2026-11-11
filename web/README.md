# Web de LOT Bot

Página pública (funciones, precios, formas de pago, prueba gratis de 24 h) y
panel **/admin** para gestionarlo todo. Hecha con Next.js y una base de datos
Postgres. Las tablas se crean solas la primera vez.

## Publicarla en Vercel (una sola vez)

1. **Importar el proyecto.** En vercel.com → *Add New… → Project* → elige el
   repositorio de LOT Bot en GitHub.
   - **Root Directory:** `web` (importante: la web está en esta carpeta).
   - Framework: Next.js (lo detecta solo). No cambies nada más.
2. **Base de datos.** En el proyecto → *Storage → Create Database → Neon
   (Postgres)* → conéctala al proyecto. Vercel añade `DATABASE_URL` sola.
3. **Variables** (*Settings → Environment Variables*):
   | Variable | Qué poner |
   |---|---|
   | `ADMIN_PASSWORD` | La contraseña de /admin (mínimo 8 caracteres; mejor 16 o más). |
   | `SESSION_SECRET` | Un texto largo y aleatorio (p. ej. 40 letras y números al azar). |
   | `SITE_URL` | La dirección de la web, p. ej. `https://lotbot.es` (sin `/` al final). |
   | `STRIPE_SECRET_KEY` | *(Opcional, para tarjeta)* clave secreta de Stripe (`sk_live_…`). |
   | `STRIPE_WEBHOOK_SECRET` | *(Opcional, para tarjeta)* secreto del webhook (`whsec_…`). |
4. **Deploy.** Pulsa *Redeploy* para que use las variables.
5. Entra en `https://tu-web/admin` con tu contraseña y sigue los avisos del
   Resumen:
   - **Planes y precios:** los que vienen son de EJEMPLO. Pon los tuyos.
   - **Formas de pago:** activa Bizum, transferencia o PayPal y escribe las
     instrucciones (tu número, IBAN o enlace). Puedes usar `{importe}` y
     `{referencia}`.
   - **Ajustes:** tu nombre o empresa, email, WhatsApp y la prueba gratis.

### Pago con tarjeta (Stripe), opcional

1. Crea una cuenta en stripe.com y copia la clave secreta en `STRIPE_SECRET_KEY`.
2. En Stripe → *Developers → Webhooks → Add endpoint*:
   `https://tu-web/api/stripe/webhook`, evento `checkout.session.completed`.
   Copia el *Signing secret* en `STRIPE_WEBHOOK_SECRET`.
3. *Redeploy*. La tarjeta aparece sola y las licencias se crean al pagar.

Sin Stripe, la tarjeta no se ofrece y los pagos (Bizum, transferencia,
PayPal) se confirman a mano en **/admin → Pedidos → «Marcar pagado»**, que
crea la licencia. El cliente la ve en la página de su pedido.

## Qué hay

| Dirección | Para qué |
|---|---|
| `/` | Portada: funciones, precios, formas de pago, prueba gratis, preguntas. |
| `/prueba` | Prueba gratis (de un solo uso: por email, por ordenador y máximo 2 por conexión cada 30 días). |
| `/comprar` | Elegir plan y forma de pago. |
| `/pedido/LOT-XXXXXXXX` | Estado del pedido, instrucciones de pago y, cuando está pagado, la licencia. |
| `/admin` | Resumen, pedidos, licencias, pruebas, clientes, planes, formas de pago, ajustes y registro. |
| `/api/license/verify` | Para que LOT Bot (escritorio) compruebe una licencia: `POST {"key", "deviceId"}`. |
| `/api/health` | Comprueba que la web y la base de datos funcionan. |

## Probar en tu ordenador

```bash
cd web
cp .env.example .env.local   # y rellénalo (base de datos de PRUEBAS)
npm install
npm run dev                  # http://localhost:3000
```

Pruebas de la API (contra la web en marcha y una base de datos de pruebas):

```bash
BASE_URL=http://localhost:3000 DATABASE_URL=postgres://… npm test
```

## Seguridad

- /admin: contraseña + cookie firmada (12 h). Tras 5 fallos desde la misma
  conexión se bloquea 15 minutos.
- La IP nunca se guarda: solo una huella para limitar abusos de la prueba.
- Con tarjeta, los datos los ve solo Stripe; esta web no los ve ni los guarda.
- No subas nunca `.env.local` ni pongas las claves en el código.
