# Licencias (fase 2)

LOT Bot comprueba la licencia contra el servidor de la web (`web/`, API v1).
El código está en `lot_bot/licensing/`.

## Piezas

| Fichero | Qué hace |
|---|---|
| `config.py` | Servidor (`https://www.lotbot.es`) y **clave pública** Ed25519 dentro del programa (`EMBEDDED_PUBLIC_KEYS`). |
| `fingerprint.py` | Huella anónima del ordenador: SHA-256 de `MachineGuid` (Windows), `IOPlatformUUID` (macOS) o `/etc/machine-id` (Linux). Nunca se envía el identificador en claro. |
| `lease.py` | Comprueba el pase `LBT1.<json>.<firma>`: firma, tipo, clave (`kh`) y ordenador (`dev`). |
| `store.py` | `config/licencia.json` en la carpeta de datos. La clave va cifrada (misma caja que las demás claves locales). |
| `client.py` | `POST /api/v1/license/{activate,refresh,deactivate}`. Separa respuestas definitivas de errores pasajeros. |
| `manager.py` | Estado (`sin_exigir`, `sin_licencia`, `activa`, `bloqueada`), renovación en segundo plano, reloj. |
| `guard.py` | Candado delante de Wallapop real: deja leer, no deja cambiar nada sin licencia. |
| `lot_bot/ui/license.py` | Pantalla de activación, franja de aviso y pestaña Configuración → Licencia. |

## Reglas

* **Activar**: la persona escribe `LOTB-XXXX-XXXX-XXXX` (se admite en minúsculas,
  con espacios o sin guiones). El servidor devuelve un pase de 72 h (nunca más
  allá de la caducidad de la licencia).
* **Renovar**: cada 4-6 h al azar, en segundo plano, y al abrir LOT Bot.
* **Sin conexión**: sigue funcionando con el último pase hasta que caduca
  (3 días). Se reintenta cada 15 min. Con menos de 24 h de margen sale un aviso.
* **Respuesta definitiva** (`LICENSE_EXPIRED`, `LICENSE_SUSPENDED`,
  `LICENSE_REVOKED`, `LICENSE_NOT_FOUND`, `DEVICE_BLOCKED`,
  `DEVICE_NOT_ACTIVATED`): bloquea al momento y borra el pase. Se sigue
  preguntando cada 30 min: si se renueva o se reactiva, vuelve sola.
* **Errores pasajeros** (sin red, 5xx, `RATE_LIMITED`, `SERVER_NOT_CONFIGURED`):
  nunca bloquean; se sigue con el pase que haya.
* **Reloj**: si la hora va más de 10 min hacia atrás respecto a la más alta
  vista, se bloquea hasta comprobar con el servidor. Un PC con la hora mal de
  fábrica se corrige con la hora del servidor.
* **Bloqueo seguro**: con la licencia no activa, el candado no deja publicar,
  editar, borrar ni enviar mensajes en Wallapop real (sí leer). La cola mira la
  licencia antes de cada anuncio: el que ya se está publicando termina
  (`publication_in_progress`), los siguientes esperan y la cola se pausa con el
  motivo «Licencia no activa…». Al volver a estar activa, sigue sola.
* **Datos**: nada de esto borra ni cambia cuentas, anuncios, fotos ni ajustes.
* **DEMO**: gratis, sin licencia y sin candado.

## Licencias en producción

La clave pública de producción (identificador `f9607729`, la misma que publica
`https://www.lotbot.es/api/v1/public-key`) ya va en `EMBEDDED_PUBLIC_KEYS`.
Por tanto **esta versión exige licencia** para usar Wallapop real (DEMO libre).

Antes de publicarla a los clientes (rama `estable`):

1. Crear en `/admin/licencias` la licencia de cada cliente actual (o que se
   creen la cuenta en `/cuenta/registro` y se suscriban; marcar a los actuales
   como «Fundador» en `/admin/clientes` para el precio especial).
2. Enviarles su clave: al abrir LOT Bot aparece la pantalla de activación.

Si algún día hay que cambiar de clave: generar otra, añadir la nueva pública a
`EMBEDDED_PUBLIC_KEYS` (se admiten varias), publicar esa versión y solo después
cambiar `LICENSE_SIGNING_KEY` en Vercel.

En el programa instalado (ejecutable) no se puede cambiar la clave pública ni
el servidor con variables de entorno. Desde el código fuente sí, para pruebas:
`LOT_BOT_LICENSE_PUBLIC_KEY` y `LOT_BOT_LICENSE_SERVER`.

> Nota honesta: quien ejecuta LOT Bot desde el **código fuente** puede
> modificarlo y saltarse cualquier comprobación local. La protección real
> llega con los ejecutables firmados (Windows `.exe`, Mac `.app`).

## Pruebas

* `tests/test_licencias.py` (sin red): activar, formato, sin conexión, todos los
  errores del servidor, pase falsificado/de otra clave/de otro ordenador,
  renovación 4-6 h, 3 días sin conexión, reinicio sin red, reloj atrasado,
  fichero manipulado o dañado, desvincular, candado, cola (pausa sin cortar el
  anuncio en curso y reanudación sola), DEMO sin licencia.
* `tests/test_licencias_servidor.py`: contra la web de verdad (Next.js +
  Postgres). Se activan con `LOT_BOT_TEST_LICENSE_SERVER` y
  `LOT_BOT_TEST_LICENSE_DB` (ver cabecera del fichero).
* CI `.github/workflows/pruebas.yml`: toda la batería y la autoprueba en
  Windows y Mac con Python 3.11. La autoprueba (`--autoprueba`) comprueba
  también la huella del ordenador y la firma Ed25519 dentro del ejecutable.

## Protección (fase 5)

Medidas defensivas, sin ofuscar el programa:

- **Alertas de posible abuso** (`/admin/alertas`, aviso en el Resumen):
  - licencia usada desde muchas conexiones distintas (más de 3 por ordenador
    permitido en 7 días); de la conexión solo se guarda una huella irreversible;
  - muchos cambios de ordenador (más de 6 en 30 días);
  - muchas claves inventadas desde una conexión (10+ en 24 h; se frena sola a 20/h);
  - un ordenador con 3 o más licencias;
  - instalación modificada (ver abajo).
  Solo avisan: el admin decide si suspender, desvincular o bloquear.
- **Número de licencia** en el informe de soporte y en el registro al
  arrancar (la clave va enmascarada). Sirve para saber de dónde viene una copia.
- **Comprobación de la instalación** (`lot_bot/licensing/integrity.py`): el
  programa instalado pide la lista FIRMADA de huellas de sus ficheros oficiales
  (la genera GitHub Actions al publicar, después de firmar) y la compara con
  los suyos. El resultado se cuenta al servidor; si no coincide, sale en
  Alertas y en Configuración → Licencia. **Nunca bloquea ni borra nada** (un
  disco dañado o un antivirus también pueden cambiar un fichero).
