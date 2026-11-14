# Operación de LOT Bot (qué hacer si…)

## Vigilancia y copias

| Qué | Dónde | Cada cuánto |
|---|---|---|
| Web, base de datos, firma de licencias y páginas principales | GitHub Actions → «Vigilancia» | Programada cada 10 min; en la práctica ~1 por hora (ver abajo) |
| Copia CIFRADA del esquema `lotbot` (30 días), **restaurada y comprobada en cada ejecución** | GitHub Actions → «Copia de seguridad» | Cada día, 03:17 UTC (GitHub puede retrasarla horas) |
| Errores de la web | Vercel → Logs / Observability | En directo |
| Posible abuso de licencias | `/admin/alertas` (y aviso en el Resumen) | En directo |

Para que GitHub te avise de un fallo: *Settings → Notifications → Actions →
«Send notifications for failed workflows only»*. Secretos de la copia:
`BACKUP_DATABASE_URL` y `BACKUP_PASSPHRASE` (guárdala también en tu gestor de
contraseñas: sin ella la copia no se puede abrir). **Sin ellos la copia sale
en rojo** (antes salía en verde sin copiar nada).

**Las tareas programadas de GitHub no son puntuales.** GitHub descarta muchos
disparos en repositorios con poca actividad: con la vigilancia «cada hora» se
ejecutaron 5 de unas 35 (12-14/11/2026, huecos de 6 a 8 h). Por eso se
programa cada 10 minutos. Solo se ejecutan desde la **rama por defecto** de
GitHub. Para avisos garantizados en minutos, añade un monitor externo gratuito
(p. ej. UptimeRobot) a `https://www.lotbot.es/api/health` con la palabra clave
`"ok":true`.

### Ensayo de la copia (sin tocar producción)

GitHub → Actions → «Copia de seguridad» → *Run workflow* → marca **Ensayo**.
Copia una base de prueba desechable, la cifra, la restaura en otra y compara.
No usa los secretos ni se conecta a la base real.

### Restaurar una copia

1. GitHub → Actions → «Copia de seguridad» → la del día → descarga el artefacto.
2. En tu ordenador, con PostgreSQL **18** (la versión de Neon) y en una base
   **vacía**, nunca la de producción:
   ```bash
   export BACKUP_PASSPHRASE='TU_CONTRASEÑA'
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in lotbot-AAAAMMDD.sql.gz.enc \
     -pass env:BACKUP_PASSPHRASE | gunzip | psql "postgres://…base-de-datos-NUEVA…"
   ```
3. Comprueba los datos y cambia `DATABASE_URL` en Vercel a la base restaurada.

Cómo se ha probado (14/11/2026): `scripts/copia_seguridad.sh` sobre un
PostgreSQL 18 con 17 tablas y ~4 000 filas, restaurado en **otro** servidor
PostgreSQL 18: mismas filas y **mismo contenido** (huella md5 de cada tabla)
en las 17. También se comprobó que se niega a restaurar en la base de origen o
en una base que ya tenga datos, y que falla con la contraseña equivocada.

## Problemas frecuentes

| Síntoma | Qué mirar | Qué hacer |
|---|---|---|
| «Vigilancia» en rojo: web caída | Vercel → Deployments / Logs | Volver al despliegue anterior (*Promote*) si el último falla. |
| Ningún cliente puede activar | `/api/health` → `signing` | Revisar `LICENSE_SIGNING_KEY` en Vercel. **No cambiarla** por otra: LOT Bot solo acepta la `f9607729`. |
| Un cliente «sin conexión» 3 días | `/admin/dispositivos` (último uso) | Que se conecte a Internet; sigue solo. |
| Cliente pagó y sigue bloqueado | `/admin/suscripciones` | Si no está, Stripe → Webhooks → reenviar el aviso. Mientras, `/admin/licencias` → «Ampliar». |
| Cobro fallido | `/admin/suscripciones` (Pago fallido) | Stripe reintenta; el cliente tiene 5 días de margen. Que cambie la tarjeta en Mi cuenta. |
| Cliente cambia de ordenador | `/admin/dispositivos` | Él mismo desde Mi cuenta (3 al mes) o tú: «Desvincular». |
| Olvidó la contraseña de Mi cuenta | `/admin/clientes` | «Enlace de contraseña» y se lo envías (vale 48 h, un uso). |
| Versión nueva con fallos | `/admin/versiones` | «Retirar» (deja de ofrecerse) o bajar el % de despliegue. |
| Alerta de licencia compartida | `/admin/alertas` | Hablar con el cliente; si sigue: suspender o bloquear ordenadores. |
| Perdiste el móvil de la verificación | Base de datos | Usa la clave guardada; o borra el ajuste `admin_2fa` (tabla `lotbot.settings`). |
| Informe de soporte de un cliente | El .zip que te envía | `sistema.txt` trae versión, licencia (n.º) y estado; `logs/` los errores. |

## Cambiar la clave de firma (solo si se filtra)

1. Generar otra (`web/scripts/generar-claves.mjs`).
2. Añadir la nueva pública a `EMBEDDED_PUBLIC_KEYS` (junto a la vieja) y
   publicar esa versión; esperar a que la tengan todos (`/admin/versiones`).
3. Cambiar `LICENSE_SIGNING_KEY` en Vercel y actualizar el `kid` en
   `.github/workflows/vigilancia.yml`.

## Datos del cliente en su ordenador

LOT Bot hace cada día, al abrirse, una copia de la base de datos local del
cliente en su carpeta de datos (`copias/lot_bot-AAAAMMDD.db`, 7 días):

- Windows: `%LOCALAPPDATA%\LOT Bot\copias`
- Mac: `~/Library/Application Support/LOT Bot/copias`

Restaurar: cerrar LOT Bot, copiar la copia elegida encima de `lot_bot.db` (en
la misma carpeta de datos) y abrir LOT Bot.

Si LOT Bot no arranca, la ventana de error tiene el botón «Crear informe para
soporte»: deja un .zip en el Escritorio con el error y los registros (sin
contraseñas ni claves).

## Diagnóstico rápido

`/admin/estado` muestra qué está configurado y qué falta (firma, Stripe,
SESSION_SECRET, versiones, descargas, verificación en dos pasos) y cuándo se
recibió el último aviso de Stripe y la última comprobación de licencia.
