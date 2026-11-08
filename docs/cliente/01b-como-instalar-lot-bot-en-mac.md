# Cómo instalar LOT Bot en un Mac

LOT Bot funciona igual en Mac que en Windows: mismas pantallas, mismo asistente,
mismo modo DEMO.

## Qué necesitas

* Un Mac con macOS 11 (Big Sur) o posterior — con chip Apple (M1, M2, M3, M4) o Intel
* **Google Chrome** o **Microsoft Edge** instalado (LOT Bot lo usa para publicar en Wallapop)
* Descargar LOT Bot (elige el de tu Mac):
  * Chip Apple (M1, M2, M3, M4):
    <https://github.com/adriacarcereny0-debug/wallapop-lotbot/releases/latest/download/LOT-Bot-macOS-arm64.dmg>
  * Procesador Intel:
    <https://github.com/adriacarcereny0-debug/wallapop-lotbot/releases/latest/download/LOT-Bot-macOS-intel.dmg>

> ¿Cuál es tu Mac? Menú  → **Acerca de este Mac** → «Chip» (Apple) o «Procesador» (Intel).

## Instalación paso a paso

### 1. Abre el .dmg

Haz doble clic en el `.dmg` descargado (en la carpeta **Descargas**). Se abre una ventana con **LOT Bot** y la
carpeta **Aplicaciones**.

### 2. Arrastra LOT Bot a Aplicaciones

Arrastra el icono de **LOT Bot** encima de **Aplicaciones**. Después ya puedes
expulsar el disco «LOT Bot» del Finder.

### 3. La primera vez: ábrelo con clic derecho

Como LOT Bot no viene de la App Store, la primera vez macOS lo bloquea:

1. Abre **Aplicaciones** en el Finder.
2. Haz **clic derecho** (o Control + clic) sobre **LOT Bot** → **Abrir**.
3. En el aviso, pulsa **Abrir**.

Si en macOS 15 (Sequoia) o posterior no aparece el botón «Abrir»:

1. Intenta abrirlo una vez (saldrá el aviso; ciérralo).
2. Ve a  → **Ajustes del Sistema** → **Privacidad y seguridad**.
3. Abajo verás «Se ha bloqueado LOT Bot» → pulsa **Abrir igualmente** y confirma.

A partir de ahí se abre con doble clic, desde el Launchpad o con Spotlight
(⌘ + espacio y escribe «LOT Bot»).

> Alternativa para usuarios avanzados, en Terminal:
> `xattr -cr "/Applications/LOT Bot.app"`

### 4. Déjalo en el Dock (recomendado)

Con LOT Bot abierto, clic derecho en su icono del Dock → **Opciones** →
**Mantener en el Dock**.

## Otra forma: la copia de GitHub (se actualiza con un clic)

Es la misma que en Windows: con ella LOT Bot avisa solo cuando hay una versión
nueva y se actualiza pulsando **Actualizar**. Se prepara una sola vez:

1. Instala **Python 3.12** desde <https://www.python.org/downloads/macos/>
   (el que trae el Mac es antiguo y no vale).
2. Instala **GitHub Desktop** (<https://desktop.github.com>), entra con tu cuenta
   de GitHub (la que tiene acceso a LOT Bot) y clona el repositorio.
   > Alternativa en Terminal: `git clone <enlace del repositorio>`. La primera vez
   > macOS ofrece instalar las «herramientas de línea de comandos»: acepta.
3. En la carpeta de LOT Bot, haz doble clic en **`iniciar_lot_bot_mac.command`**.
   La primera vez tarda unos minutos (prepara todo); después se abre en segundos.
   Si macOS pregunta si quieres abrirlo, pulsa **Abrir**.

## Comprobar que todo funciona

Si algo no va, abre **Terminal** y ejecuta:

```
"/Applications/LOT Bot.app/Contents/MacOS/LOT-Bot" --autoprueba
```

Debe terminar con «TODO CORRECTO». Si sale algún «FALLO», envíanos ese texto.

## Actualizar

* **Con la app (.dmg):** descarga el `.dmg` nuevo con el mismo enlace y arrastra
  LOT Bot a Aplicaciones → **Reemplazar**.
* **Con la copia de GitHub** (la carpeta que se abre con `iniciar_lot_bot_mac.command`):
  LOT Bot avisa solo cuando hay una versión nueva; pulsa **Actualizar** en la franja
  de arriba y se vuelve a abrir solo. También puedes hacer doble clic en
  `actualizar_lot_bot_mac.command`.

En los dos casos tus cuentas, anuncios y ajustes se conservan.

## Dónde guarda LOT Bot tus datos

En `~/Library/Application Support/LOT Bot/` (base de datos, fotos, registros y
perfiles de navegador de cada cuenta). Si borras la app, estos datos se conservan.

La configuración (`.env`) puede ir junto a la app (en **Aplicaciones**) o en
`~/Library/Application Support/LOT Bot/config/.env`.

## Diferencias con Windows

* Los atajos usan **⌘ (Cmd)** en vez de Ctrl: ⌘+A selecciona todas las fotos,
  ⌘+clic selecciona varias.
* Las fotos se arrastran desde el **Finder**.
* La clave maestra se guarda en el **Llavero** de macOS (la primera vez puede
  pedirte permiso: pulsa **Permitir siempre**).

## ¿Y en iPhone / iPad?

LOT Bot no puede funcionar en iPhone ni iPad: publica controlando Chrome/Edge
de escritorio con un perfil propio por cuenta, y iOS no permite que una app
haga eso. Usa la versión de Mac (o Windows).
