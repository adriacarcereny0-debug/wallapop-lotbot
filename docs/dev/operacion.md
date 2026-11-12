# Operación de LOT Bot (qué hacer si…)

## Vigilancia y copias

| Qué | Dónde | Cada cuánto |
|---|---|---|
| Web, base de datos, firma de licencias y páginas principales | GitHub Actions → «Vigilancia» | Cada hora |
| Copia CIFRADA del esquema `lotbot` (30 días) | GitHub Actions → «Copia de seguridad» | Cada día, 03:17 UTC |
| Errores de la web | Vercel → Logs / Observability | En directo |
| Posible abuso de licencias | `/admin/alertas` (y aviso en el Resumen) | En directo |

Para que GitHub te avise de un fallo: *Settings → Notifications → Actions →
«Send notifications for failed workflows only»*. Secretos de la copia:
`BACKUP_DATABASE_URL` y `BACKUP_PASSPHRASE` (guárdala también en tu gestor de
contraseñas: sin ella la copia no se puede abrir).

### Restaurar una copia

1. GitHub → Actions → «Copia de seguridad» → la del día → descarga el artefacto.
2. En tu ordenador:
   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in lotbot-AAAAMMDD.sql.gz.enc \
     -pass pass:'TU_CONTRASEÑA' | gunzip | psql "postgres://…base-de-datos-NUEVA…"
   ```
3. Comprueba los datos y cambia `DATABASE_URL` en Vercel a la base restaurada.
   (Probado: la restauración en una base vacía devuelve las mismas filas en
   cada tabla.)

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
