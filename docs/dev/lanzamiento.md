# Lanzamiento: pasar a los clientes actuales a la versión con licencia

1. **Preparar:** Stripe, `SESSION_SECRET`, `RELEASE_API_TOKEN`,
   `GITHUB_RELEASES_REPO`/`TOKEN` y la verificación en dos pasos de /admin.
2. **Beta (1 semana):** en `/admin/clientes` marca 2 o 3 clientes de confianza
   como «Beta». Publica una versión en canal beta (Actions → «Versión para
   clientes» → *Run workflow*, canal `beta`, con la etiqueta vX.Y.Z). Solo ellos
   la reciben.
3. **Alta de todos:** `/admin/lanzamiento` → pega `email, nombre` (uno por
   línea), plan y días gratis. Quedan como **fundadores** con su licencia. Copia
   el mensaje de cada uno y envíaselo (WhatsApp o email).
4. **Versión estable:** etiqueta vX.Y.Z en `estable`. Los que usan el código
   fuente reciben el aviso «instala la versión para clientes» en Configuración.
5. **Seguimiento:** `/admin/lanzamiento` muestra quién la ha activado y quién
   tiene cuenta. Ayuda a los que falten.
6. **Cierre:** cuando todos usen el programa instalado, quítales el acceso al
   repositorio de GitHub.
