# Propuesta: fundadores, LOT Bot Care y área del cliente

Estado: **propuesta para aprobar**. No se ha cambiado código, base de datos,
licencias ni pagos. Inspección del 14/11/2026 sobre `e216f84` y la base de
producción (solo lectura).

## 0. Dos hechos que condicionan todo

1. **La base de producción está vacía de clientes**: 0 clientes, 0 licencias,
   0 pedidos, 0 suscripciones, 0 versiones (solo los planes de ejemplo
   «mensual» 29 € y «anual» 249 €). Los clientes que ya pagaron **no están en
   el sistema**: hay que darlos de alta, no migrar filas.
2. **Tus clientes actuales usan LOT Bot 1.0.0, que no tiene licencias**
   (`v1.0.0` no incluye `lot_bot/licensing`). La 1.1.0 sí la exige para
   publicar en Wallapop. **Antes de publicar la 1.1.0, cada fundador debe
   tener su licencia perpetua y su clave**, o al actualizar se quedaría sin
   poder publicar.

## 1. Qué existe ya

| Área | Qué hay | Dónde |
|---|---|---|
| Licencias | Tipos `prueba`, `pago`, `manual`; estados activa / suspendida / revocada; **sin fecha de fin = perpetua** (ya funciona: no caduca nunca); límite de ordenadores; pases firmados de 72 h | `lib/licensing.ts`, `lib/store.ts`, migraciones 1-2 |
| Dispositivos | Alta, desvincular (cliente 3/mes, admin), bloquear, versión instalada, integridad | `devices`, `/cuenta`, `/admin/dispositivos` |
| Clientes | Cuenta con contraseña (scrypt), sesión firmada, enlace de contraseña de un uso, marca `founder`, marca `beta` | `customers`, `lib/customer-auth.ts` |
| Planes | Precio, periodo, días, ordenadores, `billing_interval` mes/año, `founder_price_cents` | `plans`, `/admin/planes` |
| Pagos | Stripe suscripción (mensual/anual) con webhook firmado, idempotente y ordenado; pedido de pago único (Stripe `payment` o Bizum/transferencia marcados a mano); portal de Stripe (tarjeta, facturas, cancelar); cupones | `lib/billing.ts`, `lib/stripe.ts`, `orders`, `subscriptions`, `stripe_events` |
| Actualizaciones | Versiones por plataforma y canal, % de despliegue, obligatoria, beta por cliente, descarga con ticket firmado de 30 min, SHA-256 | `releases`, `lib/releases.ts`, `/api/v1/updates/*` |
| Área del cliente | Licencia, suscripción (contratar / portal), descargas de la última estable, ordenadores | `/cuenta` |
| Admin | Resumen, licencias, clientes (fundador, beta), dispositivos, pedidos, pagos, suscripciones, planes, cupones, versiones, alertas, lanzamiento, historial, registro, estado, seguridad (2FA) | `/admin/*` |
| Historial | `events` (quién, qué, cuándo) y `license_events` | `/admin/registro`, `/admin/historial` |

## 2. Lo que hoy NO encaja con tu idea (importante)

| Hoy | Problema | Cambio propuesto |
|---|---|---|
| «Fundador» = **precio rebajado de suscripción** (`founder_price_cents`) | Contradice «no pagar mensualidades» | Separar: *fundador* = derecho de uso perpetuo; el precio rebajado pasa a ser un descuento opcional para Care |
| `/admin/lanzamiento` crea licencias **con caducidad (N días, 30 por defecto)** | Un fundador importado así dejaría de funcionar al mes | Modo «Fundador (perpetua)» sin fecha de fin; el modo por días queda para pruebas |
| Una suscripción de Stripe **cambia la fecha de fin de la licencia** del cliente (`syncSubscription`) | Si un fundador contratara Care, la suscripción tocaría su licencia perpetua | La suscripción de Care no toca nunca licencias; solo el servicio Care |
| Actualizaciones: basta con licencia en vigor | No hay «derechos de actualización» | Campo de derechos por licencia (ver §3) |
| No hay soporte | — | Tickets en la web (§3) |
| No hay facturas propias | Stripe las da en el portal solo para pagos con Stripe | Facturas de Stripe + registro de pagos manuales (§6) |

## 3. Cambios de datos (migraciones 8 y siguientes, todas aditivas)

Ninguna borra ni cambia columnas existentes; los datos y el programa actual
siguen funcionando.

**`licenses`** (nuevas columnas):
- `tier text NOT NULL DEFAULT 'estandar'` — `fundador`, `estandar`, `prueba`.
- `perpetual boolean NOT NULL DEFAULT false` — derecho de uso sin fin
  (además de `expires_at IS NULL`; doble seguro: una suscripción nunca podrá
  ponerle fecha de fin).
- `updates_until timestamptz` — hasta cuándo recibe versiones nuevas
  (`NULL` = todas, para siempre). Alternativa: `updates_major int` (todas las
  1.x). Recomendado para fundadores: `NULL` (todas) o la fecha que les
  prometiste.
- `terms jsonb NOT NULL DEFAULT '{}'` — condiciones prometidas al comprar
  (texto, precio pagado, fecha, ordenadores), para que nunca dependan de los
  planes del momento.

**`customers`**: `founder` ya existe; añadir `founder_since date`,
`founder_number int` (Fundador n.º 7) opcionales.

**`services`** (nueva): servicios contratables aparte de la licencia.
- `care` — LOT Bot Care, 49,99 €/mes (precio en la fila, editable).

**`subscriptions`**: añadir `product text NOT NULL DEFAULT 'licencia'`
(`licencia` | `care`). Las de `care` nunca tocan `licenses`.

**`payments`** (nueva): historial unificado de cobros (Stripe y manuales):
cliente, concepto, importe, IVA, estado, `stripe_invoice_id`, URL de la
factura, fecha.

**`support_tickets`** y **`support_messages`** (nuevas): asunto, estado
(abierta / esperando cliente / resuelta), prioridad (`care` = prioritaria),
mensajes del cliente y del admin, adjuntos opcionales (informe de soporte de
LOT Bot).

**`release_notes`**: no hace falta tabla: `releases.notes` ya guarda las
novedades; el historial se lista desde `releases`.

## 4. Alta de los clientes actuales sin perder nada

1. Preparar la lista (email, nombre, fecha y precio de compra, ordenadores
   prometidos, qué actualizaciones se les prometieron).
2. `/admin/lanzamiento` en modo **Fundador**: crea el cliente con
   `founder = true` y una licencia `tier = fundador`, `perpetual = true`,
   `expires_at = NULL`, `updates_until` según lo prometido y `terms` con sus
   condiciones. Repetir la importación no duplica (ya está así).
3. Cada fundador recibe su clave y un enlace para crear su contraseña de
   «Mi cuenta» (ya existe el enlace de un solo uso).
4. **Solo entonces** publicar la 1.1.0. Con la clave, actualizan e introducen
   la clave una vez; si no la tienen a mano, la ven en «Mi cuenta».
5. Si alguno no la activa, `/admin/lanzamiento` ya muestra quién falta.

## 5. Garantías para fundadores (que no paguen otra vez)

- Licencia perpetua: `perpetual = true` y sin fecha de fin. El código de
  Stripe solo podrá modificar licencias `tier <> 'fundador'` y nunca las
  `perpetual` (comprobación en código **y** restricción en la base:
  `CHECK (NOT perpetual OR expires_at IS NULL)`).
- Actualizaciones: `checkForUpdate` y las descargas de «Mi cuenta» miran
  `updates_until` (no el plan ni la suscripción). Cambiar precios o planes
  no afecta a licencias existentes: las condiciones viven en la licencia.
- Care es opcional: contratarlo o cancelarlo no toca la licencia (pruebas
  automáticas específicas: cancelar Care → licencia intacta; impago de Care →
  licencia intacta).
- Cambios en sus condiciones solo desde el admin, con registro en el
  historial (quién y cuándo).
- Términos: añadir en `/terminos` una sección «Licencias de fundador» que
  recoja estas garantías.

## 6. Stripe, de forma segura y legal

- **La cuenta de Stripe la abre y verifica el titular real del negocio**
  (persona mayor de edad o empresa, con su identidad y cuenta bancaria). No
  se automatiza ni se salta ningún requisito de Stripe. Claude no crea ni
  activa cuentas.
- Probar todo primero con claves de **modo prueba** (`sk_test_…`).
- Care = suscripción de Stripe (`mode: subscription`) con un precio de
  Stripe fijo (Product «LOT Bot Care») en vez de `price_data` en línea, para
  que facturas y portal muestren el nombre correcto.
- Renovaciones, reintentos de cobro, cancelación al final del periodo y
  facturas: los gestiona Stripe; el portal del cliente ya está integrado
  (cancelar Care desde «Mi cuenta» → portal).
- Webhook: el mismo de hoy (firmado, idempotente, en orden), enrutando por
  `metadata.product` (`licencia` | `care`).
- Facturas: activar en Stripe la factura para cada cobro y los datos
  fiscales del cliente (NIF opcional). IVA: Stripe Tax o tipo fijo del 21 %.
  **Consultar con una gestoría** las obligaciones de facturación en España
  (incluido el sistema VERI*FACTU) antes de cobrar.
- Derecho de desistimiento (14 días) y condiciones de Care en `/terminos`.
- Ninguna clave de Stripe en el repositorio; solo en Vercel.

## 7. Servicios externos y costes orientativos (verificar precios actuales)

| Servicio | Para qué | Coste orientativo |
|---|---|---|
| Stripe | Cobros, facturas, portal | Sin cuota; comisión por cobro con tarjeta europea (≈1,5 % + 0,25 €, ver stripe.com/es/pricing). Stripe Tax: comisión adicional por transacción |
| Vercel | Web | **Hobby no permite uso comercial**: con cobros reales hace falta Pro (≈20 $/mes por miembro). Comprobar el plan actual |
| Neon | Base de datos | Plan gratuito suficiente hoy; plan de pago si crece o para más historial de restauración |
| Email (Resend, Postmark…) | Avisos de tickets, recuperar contraseña, recibos | Gratis en volúmenes bajos; ≈20 $/mes después |
| GitHub Actions | CI y copias | Repositorio privado: minutos gratis limitados; **los de macOS cuentan ×10** |
| Apple Developer | Firma y notarización Mac | 99 $/año |
| Firma de Windows | Quitar «editor desconocido» | ≈100-400 €/año según proveedor |
| Gestoría | Facturación e IVA | Según gestoría |

## 8. Fases (cada una se puede publicar sola, sin romper lo anterior)

| Fase | Qué | Riesgo |
|---|---|---|
| **A. Fundadores** (antes de la 1.1.0) | Migración aditiva (`tier`, `perpetual`, `updates_until`, `terms`); lanzamiento en modo Fundador perpetuo; protección para que Stripe no toque licencias perpetuas; «Fundador» visible en Mi cuenta y admin; pruebas | Bajo: aditivo, sin pagos |
| **B. Derechos de actualización** | `updates_until` en comprobación y descargas; historial de versiones y novedades en Mi cuenta | Bajo |
| **C. Soporte** | Tickets en Mi cuenta y admin; avisos por email | Bajo (necesita servicio de email) |
| **D. LOT Bot Care** | Servicio, suscripción con `product = care`, contratar/cancelar, soporte prioritario, pagos en Mi cuenta | Medio: pagos reales; todo en modo prueba antes |
| **E. Facturas y pagos** | Tabla `payments`, facturas de Stripe, registro de pagos manuales | Medio: requisitos fiscales |
| **F. Admin** | Filtros: fundadores, Care activo, pagos, tickets; condiciones especiales; historial | Bajo |

Cada fase: rama propia → pruebas (incluida la de que cancelar o impagar Care
no toca ninguna licencia) → vista previa (cuando exista base de datos propia
de previews) → tu aprobación → producción. Recomendado hacer antes la
separación de la base de datos de previews (`separar-bd-previews.md`), porque
estas fases traen migraciones nuevas.
