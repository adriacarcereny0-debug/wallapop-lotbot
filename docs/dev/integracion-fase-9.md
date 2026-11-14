# Integrar la fase 9 en producción

Fecha: 14/11/2026. Rama candidata: `claude/integracion-fase-9`.
Nada de lo descrito aquí se ha hecho en producción: es el plan para cuando
se autorice.

## 1. Situación comprobada (no supuesta)

| Qué | Estado real |
|---|---|
| Rama que Vercel publica en www.lotbot.es | `claude/funny-ritchie-rokcir` (commit `4e918ea`, fases 7 y 8) |
| Rama por defecto de GitHub | **también** `claude/funny-ritchie-rokcir` |
| Tareas programadas (Vigilancia, Copia de seguridad) | ya se ejecutan desde esa rama y salen en verde |
| `claude/fase-9-auditoria-final` respecto a producción | 3 commits por delante, 0 por detrás: unión sin conflictos |
| `claude/integracion-fase-9` | producción + un commit de unión (`--no-ff`) con la fase 9 + documentación |
| Esquema de la base de datos de producción | versión 7; la fase 9 **no añade migraciones** |
| Verificación en dos pasos en producción | a medio configurar (`enabled=false`): no hay riesgo de quedarse fuera de /admin |
| Variables de producción en Vercel | `ADMIN_PASSWORD`, `SESSION_SECRET`, `SITE_URL`, `LICENSE_SIGNING_KEY` y la base de datos. Faltan las de Stripe y las de actualizaciones (opcionales) |
| Vistas previas de Vercel | usan **la misma base de datos que producción** (variables de Neon en *Preview* y *Production*), sin claves de firma ni de admin |

### Qué rama necesita cada cosa (no confundirlas)

- **Vercel (web en producción)** → la *Production Branch* del proyecto: hoy
  `claude/funny-ritchie-rokcir`.
- **GitHub Actions programadas** (`vigilancia.yml`, `copia-seguridad.yml`)
  → la **rama por defecto de GitHub**: hoy también `claude/funny-ritchie-rokcir`.
- **Pruebas y compilación** (`pruebas.yml`, `build-macos.yml`) → cualquier
  push a `claude/**`, `main` o `estable`.
- **Publicar una versión de LOT Bot** (`publicar-version.yml`) → **solo** una
  etiqueta `vX.Y.Z`. Un push a una rama nunca publica.

Hoy las dos primeras coinciden, así que **unir la fase 9 en
`claude/funny-ritchie-rokcir` actualiza a la vez la web y las tareas
programadas**. Si más adelante se cambia la rama de producción de Vercel a
`estable`, **no** hay que cambiar la rama por defecto de GitHub: las tareas
programadas deben seguir en `claude/funny-ritchie-rokcir`, que tiene sus
ficheros (`estable` no los tiene).

## 2. Plan de integración

1. **Hecho.** Crear `claude/integracion-fase-9` desde producción y unir la
   fase 9 con un commit de unión (`git merge --no-ff`).
2. **Hecho.** Ejecutar todas las pruebas sobre esa rama (ver §5) y comprobar
   la vista previa de Vercel.
3. **Con autorización.** Avanzar `claude/funny-ritchie-rokcir` hasta el
   commit exacto probado (*fast-forward*, sin reescribir historia):
   `git push origin <commit probado>:claude/funny-ritchie-rokcir`.
   Vercel despliega solo. Si alguien hubiera subido algo a producción
   entretanto, el push se rechaza (no es *fast-forward*) y se repite el
   paso 1.
4. **Justo después** (5 minutos): las comprobaciones de §4.
5. **No forma parte de este paso**: publicar la 1.1.0, cambiar la rama de
   Vercel, añadir variables. Cada cosa, cuando se autorice.

### Marcha atrás

- Rápida (segundos, sin código): Vercel → Deployments → el despliegue
  anterior de producción → **Instant Rollback**.
- Definitiva: `git revert -m 1 <commit de unión>` en
  `claude/funny-ritchie-rokcir` y push (sin reescribir historia).
- La base de datos no necesita marcha atrás: la fase 9 no cambia el esquema.
  Las filas nuevas que escribe (`login_attempts` con `scope='pedido'`,
  eventos `clave_inexistente` de la API antigua) son compatibles con el
  código anterior.

## 3. Riesgos y efectos esperados

| Riesgo / efecto | Gravedad | Detalle y mitigación |
|---|---|---|
| **Se cierran las sesiones abiertas de /admin** | Esperado | La firma de la cookie incluye ahora la contraseña. Tras el despliegue hay que volver a entrar una vez. |
| La verificación en dos pasos | Bajo | Está sin activar en producción. Si se activa después, ya se cifra con `SESSION_SECRET`; las claves antiguas se siguen aceptando y se recifra. |
| Next.js 15.5.27 → 15.5.29 y PostCSS 8.5.32 forzado | Bajo | Versión de parche. Compilación sin avisos; las 66 pruebas web pasan con el servidor compilado. |
| Freno de 20 pedidos/hora por conexión | Bajo | Si un local comparte IP (oficina, wifi pública) y hace >20 pedidos en una hora, el 21.º recibe 429 con mensaje. Muy improbable con el volumen actual. |
| API antigua `/api/license/verify` más estricta | Bajo | Rechaza identificadores de ordenador inválidos (400) y frena claves inventadas (429). LOT Bot actual no la usa; una copia muy antigua con un identificador no válido dejaría de validar. |
| **Las vistas previas usan la base de datos de producción** | Medio (ya existía) | Cualquier rama empujada a GitHub despliega una vista previa conectada a los datos reales (sin firma ni admin). Recomendado: quitar las variables de Neon del entorno *Preview* o usar una rama de Neon para *Preview*. No se ha cambiado (requiere tu autorización). |
| **No hay copia de seguridad de la base de datos** | Alto (ya existía, no lo causa la fase 9) | La «Copia de seguridad» del 13/11 salió en verde pero **saltó** los pasos de copiar, cifrar y subir: faltan `BACKUP_DATABASE_URL` y `BACKUP_PASSPHRASE`. Recomendado: añadirlos **antes** del despliegue y lanzar el flujo a mano una vez. Neon guarda además 6 h de historial (restauración a un punto anterior). |
| La «vigilancia horaria» va cada ~6 h | Bajo | GitHub retrasa las tareas programadas en repositorios con poca actividad: 5 ejecuciones en 28 h, todas en verde. Para avisos más rápidos, un servicio externo (p. ej. UptimeRobot sobre `/api/health`). |
| Filas de `login_attempts` con `scope='pedido'` | Muy bajo | Se borran las de más de un día al entrar en /admin. |
| Lo que **no** cambia | — | LOT Bot instalado en los clientes: no recibe nada hasta publicar una versión. Licencias, pases y clave pública (`f9607729`): sin cambios. |

## 4. Comprobaciones

### Antes de autorizar
- [ ] CI de `claude/integracion-fase-9` en verde: «Pruebas Windows y Mac», «App para Mac» y «Versión para clientes» (ejecutado a mano, sin publicar).
- [ ] La vista previa de esa rama abre la portada, `/prueba`, `/terminos` y `/cuenta/entrar`, y `/api/health` responde `"ok":true` y `"schema":7`.
- [ ] Nadie ha subido nada a `claude/funny-ritchie-rokcir` desde `4e918ea`.
- [ ] Sabes tu `ADMIN_PASSWORD` (habrá que volver a entrar).

### Justo después del despliegue
- [ ] `https://www.lotbot.es/api/health` → `"ok":true`, `"schema":7`, `"signing":"configurada"`.
- [ ] `https://www.lotbot.es/api/v1/public-key` → `"kid":"f9607729"`.
- [ ] Entrar en `/admin` y abrir **Estado del sistema** (nuevo): muestra qué está configurado.
- [ ] Abrir **Licencias**, **Historial** y **Registro**.
- [ ] Lanzar a mano el flujo «Vigilancia» en GitHub → verde.
- [ ] Un LOT Bot con licencia: Configuración → Licencia → «Comprobar ahora» → activa.

## 5. Pruebas en la rama de integración (resultados reales, 14/11)

Sobre el commit de unión `34540fe` (mismo contenido que la fase 9):

| Qué | Resultado |
|---|---|
| `npm ci` limpio | Next.js **15.5.29**, PostCSS (dentro de Next) **8.5.32** |
| `npm audit` | **0 vulnerabilidades** |
| `tsc --noEmit` y `next build` | sin errores ni avisos |
| Pruebas web (servidor compilado + Postgres) | **66/66** |
| Pruebas de Python (todas menos el navegador real) | **709 pasadas, 3 omitidas, 0 fallos** (incluye las 10 contra el servidor de licencias) |
| Autoprueba del programa en este contenedor | todo correcto salvo «Navegador»: **falla igual con el código actual de producción** (el contenedor no tiene el Chromium que espera Playwright); en el CI se ejecuta con Chrome real |
| Vista previa de Vercel (`web-ejt7te3d1-…vercel.app`) | portada, `/prueba`, `/terminos`, `/cuenta/entrar` → 200; `/api/health` → `ok`, esquema 7. Sin firma, admin ni cuentas (esas variables solo están en producción): esperado |
| CI en GitHub | ver el historial de Actions de la rama `claude/integracion-fase-9` |

Solo se hicieron peticiones de lectura a la vista previa, porque usa la base
de datos de producción.

## 6. Migraciones y variables

**Migraciones.** Son automáticas: al primer acceso a la base de datos, la web
aplica las que falten (tabla `lotbot.schema_migrations`, con bloqueo para que
dos servidores no las apliquen a la vez). La fase 9 no añade ninguna; la
última es la 7 (`customers.beta`) y producción ya la tiene.

**Variables de la web** (Vercel → Settings → Environment Variables; ejemplo
completo en `web/.env.example`, explicación en `web/README.md`):

| Variable | Necesaria | En producción |
|---|---|---|
| `DATABASE_URL` | sí | sí (Neon) |
| `LICENSE_SIGNING_KEY` | sí | sí |
| `ADMIN_PASSWORD` | sí | sí |
| `SESSION_SECRET` | sí | sí |
| `SITE_URL` | sí | sí |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | para cobrar con tarjeta | no |
| `RELEASE_API_TOKEN`, `GITHUB_RELEASES_REPO`, `GITHUB_RELEASES_TOKEN` | para actualizaciones | no |
| `BILLING_GRACE_DAYS` (5), `LICENSE_LEASE_HOURS` (72) | opcionales | no (valores por defecto) |

**Secretos de GitHub** (Settings → Secrets → Actions): `RELEASE_API_TOKEN`
(publicar versiones), `BACKUP_DATABASE_URL` y `BACKUP_PASSPHRASE` (copia
diaria; sin ellos el flujo sale en verde pero **no hace copia**, solo avisa),
`WIN_CERT_*` / `MAC_CERT_*` (firma, opcionales).
