# Web de LOT Bot

Página pública (funciones, precios, formas de pago, prueba gratis de 24 h) y
panel **/admin** para gestionarlo todo. Hecha con Next.js y una base de datos
Postgres. Las tablas se crean solas la primera vez.

## Publicarla en Vercel (una sola vez)

1. **Importar el proyecto.** En vercel.com → *Add New… → Project* → elige el
   repositorio de LOT Bot en GitHub.
   - **Root Directory:** `web` (importante: la web está en esta carpeta).
   - Framework: Next.js (lo detecta solo). No cambies nada más.
2. **Base de datos (Supabase).** Crea un proyecto en supabase.com (región
   Europa, p. ej. Frankfurt). En *Project Settings → Database → Connection
   string* copia la de **Transaction pooler** (puerto 6543) con tu contraseña.
   Las tablas se crean solas y quedan protegidas con RLS (la API pública de
   Supabase no puede leerlas). *(También funciona con Neon.)*
3. **Clave de firma de licencias.** En tu ordenador, dentro de `web/`:
   `node scripts/generar-claves.mjs`. Guarda la clave SECRETA en tu gestor de
   contraseñas y en Vercel; la PÚBLICA es la que llevará LOT Bot.
4. **Variables** (*Settings → Environment Variables*):
   | Variable | Qué poner |
   |---|---|
   | `DATABASE_URL` | La cadena de conexión de Supabase (Transaction pooler). |
   | `LICENSE_SIGNING_KEY` | La clave SECRETA de firma (paso 3). |
   | `ADMIN_PASSWORD` | La contraseña de /admin (mínimo 8 caracteres; mejor 16 o más). |
   | `SESSION_SECRET` | Un texto largo y aleatorio (p. ej. 40 letras y números al azar). |
   | `SITE_URL` | La dirección de la web, p. ej. `https://lotbot.es` (sin `/` al final). |
   | `STRIPE_SECRET_KEY` | *(Para tarjeta y suscripciones)* clave secreta de Stripe (`sk_live_…`). |
   | `STRIPE_WEBHOOK_SECRET` | *(Opcional, para tarjeta)* secreto del webhook (`whsec_…`). |
   | `RELEASE_API_TOKEN` | *(Actualizaciones)* texto aleatorio de 32+ caracteres. El mismo va en GitHub → Secrets como `RELEASE_API_TOKEN`: con él GitHub Actions registra cada versión. |
   | `GITHUB_RELEASES_REPO` | *(Actualizaciones)* `usuario/repositorio` donde se publican las versiones. |
   | `GITHUB_RELEASES_TOKEN` | *(Actualizaciones, repositorio privado)* token de GitHub de solo lectura (*fine-grained*, permiso «Contents: Read» en ese repositorio). Con él la web entrega las descargas sin hacer público el repositorio. |
5. **Deploy.** Pulsa *Redeploy* para que use las variables. Comprueba
   `https://tu-web/api/health`: debe decir base de datos «conectada» y firma
   «configurada».
6. Entra en `https://tu-web/admin` con tu contraseña y sigue los avisos del
   Resumen:
   - **Planes y precios:** los que vienen son de EJEMPLO. Pon los tuyos.
   - **Formas de pago:** activa Bizum, transferencia o PayPal y escribe las
     instrucciones (tu número, IBAN o enlace). Puedes usar `{importe}` y
     `{referencia}`.
   - **Ajustes:** tu nombre o empresa, email, WhatsApp y la prueba gratis.

### Suscripciones con tarjeta (Stripe)

Los planes mensual y anual se cobran como **suscripción**: se renuevan solos y
el cliente cambia la tarjeta, ve sus facturas o cancela desde **Mi cuenta**
(portal de Stripe). No hace falta crear productos ni precios en Stripe: se
crean solos con el precio de cada plan de **/admin → Planes**.

1. Crea la cuenta en stripe.com (empieza en **modo de prueba**).
2. Copia la clave secreta (*Developers → API keys*, `sk_test_…` o `sk_live_…`)
   en `STRIPE_SECRET_KEY`.
3. *Developers → Webhooks → Add endpoint*: `https://www.lotbot.es/api/stripe/webhook`
   con estos eventos:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `customer.subscription.paused`,
   `customer.subscription.resumed`.
   Copia el *Signing secret* (`whsec_…`) en `STRIPE_WEBHOOK_SECRET`.
4. *Settings → Billing → Customer portal*: activa «cambiar método de pago»,
   «ver facturas» y «cancelar suscripción» (al final del periodo).
5. *Settings → Billing → Subscriptions and emails → Manage failed payments*:
   reintentos durante unos días y, al acabar, «marcar como impagada» (unpaid).
6. IVA: activa *Stripe Tax* o pon el precio con IVA incluido en tus planes.
7. *Redeploy*.

Qué pasa con la licencia (lo aplica la web sola con los avisos de Stripe):

| En Stripe | Licencia |
|---|---|
| Activa / en prueba | Vale hasta el fin del periodo pagado **+ 5 días** de margen |
| Pago fallido (*past_due*) | Sigue funcionando hasta fin de periodo + 5 días |
| Cancelada al final del periodo | Vale hasta el fin del periodo (sin margen) |
| Cancelada / caducada | Termina |
| Impagada (*unpaid*) / en pausa | Suspendida «Impago (Stripe)»; al pagar vuelve sola |

- El cliente conserva **siempre la misma clave**: al suscribirse se aprovecha
  la de su prueba gratis o la de una suscripción anterior.
- Una suspensión o revocación hecha a mano en /admin no la deshace Stripe.
- **Precio de fundador**: en /admin → Planes pon el «Precio de fundador» y en
  /admin → Clientes marca a cada cliente actual como «Fundador».
- El margen se cambia con `BILLING_GRACE_DAYS` (por defecto 5).

### Cuentas de cliente (/cuenta)

El cliente entra con email y contraseña (guardada con scrypt; sesión firmada
con `SESSION_SECRET`, que es obligatorio). Ve su licencia, sus ordenadores
(puede desvincular uno, hasta 3 veces al mes) y su suscripción.

- Quien paga sin tener cuenta pone su contraseña al volver del pago.
- Un cliente de antes (prueba o compra) crea su cuenta con su email **y una de
  sus claves de licencia**, para que nadie se quede con la cuenta de otro.
- Si un email ya es cliente, el pago con tarjeta se hace desde Mi cuenta.
- No hay envío de emails: para recuperar la contraseña, en /admin → Clientes
  pulsa «Enlace de contraseña» (un solo uso, 48 h) y envíaselo.

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
| `/api/v1/license/*` | Licencias para LOT Bot (ver abajo). |
| `/api/license/verify` | Comprobación sencilla antigua (se mantiene por compatibilidad). |
| `/api/health` | Comprueba que la web y la base de datos funcionan. |

## API de licencias v1 (la usa LOT Bot)

Todas son `POST` con JSON:
`{"key": "LOTB-XXXX-XXXX-XXXX", "device": {"fingerprint": "…", "name": "…", "os": "…", "app_version": "…"}}`

| Ruta | Para qué |
|---|---|
| `/api/v1/license/activate` | Activa este ordenador (gasta una plaza si es nuevo). |
| `/api/v1/license/refresh` | Renueva el pase de un ordenador ya activado (al abrir y cada pocas horas). |
| `/api/v1/license/deactivate` | Libera este ordenador (máximo 3 cambios al mes). |
| `GET /api/v1/public-key` | Clave pública para comprobar los pases. |

Respuesta correcta: `{"ok": true, "token": "LBT1.…", "lease_expires_at": "…", "license": {…}}`.
El **pase** (`token`) está firmado con Ed25519 y dura **72 h** (margen sin
conexión de 3 días), nunca más que la propia licencia. Lleva el ordenador al
que pertenece: copiado a otro ordenador no sirve.

Errores: `{"ok": false, "code": "…", "message": "…"}` con estos códigos:
`LICENSE_NOT_FOUND`, `LICENSE_EXPIRED`, `LICENSE_SUSPENDED`, `LICENSE_REVOKED`,
`DEVICE_LIMIT`, `DEVICE_BLOCKED`, `DEVICE_NOT_ACTIVATED`, `TRIAL_ALREADY_USED`,
`TOO_MANY_CHANGES`, `RATE_LIMITED`, `INVALID_REQUEST`, `SERVER_NOT_CONFIGURED`.

Reglas: mensual 1 ordenador, anual 2 (lo dice cada plan); la prueba gratis es
de un solo uso también por ordenador; 20 claves inventadas por hora desde una
misma conexión bloquean esa conexión una hora; más de 6 ordenadores nuevos al
día en una licencia se frenan.

## Probar en tu ordenador

```bash
cd web
cp .env.example .env.local   # y rellénalo (base de datos de PRUEBAS)
npm install
npm run dev                  # http://localhost:3000
```

Pruebas de la API (contra la web en marcha y una base de datos de pruebas):

```bash
# La web de pruebas debe arrancar con STRIPE_WEBHOOK_SECRET=whsec_pruebas_lotbot
# (y STRIPE_SECRET_KEY=sk_test_falsa): las pruebas mandan avisos de Stripe firmados.
BASE_URL=http://localhost:3000 DATABASE_URL=postgres://… STRIPE_WEBHOOK_SECRET=whsec_pruebas_lotbot npm test
```

## Seguridad

- Licencias: pases firmados con Ed25519. La clave secreta solo está en
  Vercel; sin ella nadie puede fabricar un pase válido.
- Supabase: todas las tablas con RLS activado y sin políticas públicas.
- /admin: contraseña + cookie firmada (12 h). Tras 5 fallos desde la misma
  conexión se bloquea 15 minutos.
- La IP nunca se guarda: solo una huella para limitar abusos de la prueba.
- Con tarjeta, los datos los ve solo Stripe; esta web no los ve ni los guarda.
- No subas nunca `.env.local` ni pongas las claves en el código.
