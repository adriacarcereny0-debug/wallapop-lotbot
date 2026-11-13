# Auditoría final de LOT Bot (fase 9)

Rama: `claude/fase-9-auditoria-final`. Fecha: 13/11/2026.
Método: revisión del código del repositorio (programa de escritorio, web,
flujos de GitHub Actions), auditoría de dependencias (`npm audit`,
`pip-audit`) y ejecución real de todas las pruebas. Nada de producción se ha
tocado: esta rama no despliega a www.lotbot.es (Vercel publica a producción
desde `claude/funny-ritchie-rokcir`; las ramas nuevas solo crean vistas previas).

---

## 1. Problemas críticos (corregidos)

| # | Problema | Riesgo | Corrección |
|---|---|---|---|
| C1 | **Next.js 15.5.27 con una vulnerabilidad crítica** (GHSA-2464-fhr4-w9xw, ejecución remota de código en la optimización de imágenes con SVG) y otra de denegación de servicio en Server Actions (GHSA-p3m5-59mp-jv5r). PostCSS interno con 4 avisos (alto). | Toma de control o caída de la web. | Next.js → **15.5.29** (parche, sin cambios de API) y PostCSS forzado a **8.5.32** (`overrides`). `npm audit`: **0 vulnerabilidades**. |
| C2 | **La comprobación antigua de licencias (`/api/license/verify`) no tenía límite de intentos** ni validaba la huella del ordenador: permitía probar claves sin freno y ocupar plazas de ordenador con cualquier texto. LOT Bot ya no la usa, pero seguía abierta. | Adivinar claves; dejar clientes sin plaza. | Mismas protecciones que la API v1: huella válida obligatoria, cada clave inventada cuenta y a las 20 por hora desde una conexión responde 429. Se mantiene por compatibilidad. |
| C3 | **Bloqueo de /admin al añadir `SESSION_SECRET`**: el secreto de la verificación en dos pasos se cifraba con `SESSION_SECRET` o, si faltaba, con `ADMIN_PASSWORD`. Al añadir `SESSION_SECRET` (lo recomendado) ya no se podía leer y nadie podía entrar. | Quedarse fuera del panel. | Se prueban las claves posibles y se vuelve a cifrar con la actual al entrar. Si no se puede leer, mensaje claro en vez de error 500. **Comprobado de verdad**: activada sin `SESSION_SECRET` → servidor reiniciado con `SESSION_SECRET` → se entra y el secreto queda recifrado. |

## 2. Problemas importantes (corregidos)

| # | Problema | Corrección |
|---|---|---|
| I1 | Cambiar `ADMIN_PASSWORD` **no cerraba las sesiones abiertas** de /admin (12 h). | La firma de la sesión incluye la contraseña: al cambiarla se cierran todas. |
| I2 | **No había guía de primeros pasos** dentro de LOT Bot para clientes sin conocimientos. | Nueva guía «Primeros pasos» (licencia, cuenta de Wallapop, anuncio principal, fotos, primera publicación). LOT Bot marca solo lo hecho; «Ir» abre cada pantalla. Sale al abrir mientras falte algo (se puede quitar) y está en Configuración → Acerca de. |
| I3 | Si el llavero del sistema no respondía: (a) LOT Bot decía «sin licencia» sin explicar por qué; (b) el aviso se escribía en el registro **en cada consulta** (varias por minuto); (c) activar en esa sesión guardaba la clave cifrada con una clave temporal y **se perdía al reiniciar**. | Mensaje claro («el llavero no responde: cierra y abre LOT Bot»), un solo aviso, y en esa sesión la clave se usa sin guardarla mal (se sigue renovando). |
| I4 | Si LOT Bot **no arrancaba**, el cliente no podía mandar un informe (el botón está dentro del programa). | Botón «Crear informe para soporte» en las ventanas de error grave (arranque y errores inesperados). Mismo filtro de secretos; sin base de datos ni claves. |
| I5 | **Los datos del cliente (SQLite local) no tenían copia de seguridad.** Un fichero dañado = perderlo todo. | Copia diaria automática al abrir (`copias/lot_bot-AAAAMMDD.db`, 7 días), con la API de copia de SQLite (segura con la base abierta) y comprobación de integridad. |
| I6 | Panel: sin filtro de licencias por estado, sin historial de activaciones, registro sin filtros, sin vista de diagnóstico. | Filtro Activas/Caducadas/Suspendidas/Revocadas; **Historial de activaciones**; Registro filtrable por «quién» (admin, web, stripe, github…) y texto; **Estado del sistema** (qué está configurado y qué falta, con cómo arreglarlo). |
| I7 | `/api/checkout` sin freno: se podían crear pedidos y clientes en masa. | Máximo 20 pedidos por hora desde una conexión (429 con mensaje). |

## 3. Mejoras recomendadas (pendientes, necesitan una decisión o un servicio externo)

1. **Producción se publica desde la rama de desarrollo** (`claude/funny-ritchie-rokcir`). Cambiar en Vercel → Settings → Git → *Production Branch* a `estable` (o `main`), para que nada llegue a clientes sin querer.
2. **Envío de emails** (Resend, Postmark…): recuperar contraseña sin intervención, recibos y avisos de cobro fallido. Hoy se hace con el «Enlace de contraseña» del admin.
3. **Certificados de firma** (Windows Authenticode y Apple Developer ID + notarización): sin ellos Windows avisa de «editor desconocido» y en Mac hay que abrir con clic derecho la primera vez. El flujo ya los usa si se ponen los secretos.
4. **Base de datos propia** para LOT Bot (hoy comparte Neon con el CRM, separada por el esquema `lotbot`).
5. **Rama por defecto de GitHub**: las tareas programadas (vigilancia y copia de seguridad) solo se ejecutan desde ella; hay que llevar el código allí.
6. Dependencia indirecta `opentelemetry-api`: el entorno local tenía la 1.45.1 (CVE-2026-126360); las instalaciones nuevas ya traen la 1.45.2 corregida (comprobado en el CI de Windows).
7. Prueba de navegador real (`tests/test_real_browser_flow.py`): en este contenedor tarda demasiado por la red (pasa igual con el código anterior a los cambios); se ejecuta en Windows y Mac en el CI.

## 4. Lo que ya está bien (comprobado, no supuesto)

- **Licencias**: pases Ed25519 de 72 h, renovación 4-6 h, 3 días sin conexión, reloj atrasado, fichero manipulado o copiado a otro PC, todos los errores del servidor: pruebas sin red + **10 pruebas contra el servidor real**, todas correctas. La app de producción tiene la clave pública `f9607729` (la misma que publica www.lotbot.es).
- **Bloqueo seguro**: el anuncio en curso termina, la cola se pausa y sigue sola al reactivar; DEMO libre; datos intactos (pruebas de la cola).
- **Stripe** (sin claves reales todavía): webhook firmado, idempotente, en orden; impago con 5 días de margen, cancelación, impagada → suspendida, reactivación, misma clave siempre (pruebas con avisos firmados).
- **Cuentas de cliente**: scrypt, sesión firmada con versión, límite de intentos, vinculación con clave, enlaces de un solo uso.
- **Actualizaciones**: pase firmado + SHA-256; instalador rechazado si no cuadra (comprobado de punta a punta con descarga real por HTTPS); Windows: instalar, actualizar encima y desinstalar **sin perder datos** en el CI; Mac: sustitución de la app con firma comprobada en el CI.
- **Protección**: alertas de abuso, número de licencia en informes, comprobación de la instalación (solo informa).
- **Admin**: dos pasos (vector oficial RFC 6238), cupones, resumen de negocio, versiones, alertas, lanzamiento.
- **Copias de la web**: copia cifrada + **restauración probada** (mismas filas en cada tabla); vigilancia horaria probada contra producción.
- **Cola y multicuenta**: pruebas de ritmo, verificación (CAPTCHA: la completa la persona, nunca se intenta saltar), duplicados, «sin confirmar», fotos que faltan, hilos por cuenta.

---

## 5. Pruebas ejecutadas (resultados reales)

Ver la entrega final de la fase (resumen al usuario) para las cifras exactas de
esta ejecución.
