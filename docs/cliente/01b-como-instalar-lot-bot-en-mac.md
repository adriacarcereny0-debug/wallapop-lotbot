# Cómo instalar LOT Bot en un Mac

LOT Bot funciona igual en Mac que en Windows: mismas pantallas, mismo asistente,
mismo modo DEMO.

## Qué necesitas

* Un Mac con macOS 11 (Big Sur) o posterior — con chip Apple (M1, M2, M3, M4) o Intel
* **Google Chrome** o **Microsoft Edge** instalado (LOT Bot lo usa para publicar en Wallapop)
* El fichero `LOT-Bot-macOS.dmg` que te hemos entregado

> Usa el `.dmg` que corresponde a tu Mac: **arm64** para chip Apple, **intel** para
> procesador Intel. Lo ves en  → **Acerca de este Mac** → «Chip» o «Procesador».

## Instalación paso a paso

### 1. Abre el .dmg

Haz doble clic en `LOT-Bot-macOS.dmg`. Se abre una ventana con **LOT Bot** y la
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
