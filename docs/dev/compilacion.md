# Generar LOT-Bot.exe

El cliente final no tiene Python ni herramientas de desarrollo: recibe una carpeta con
un ejecutable y hace doble clic.

## Solución elegida: PyInstaller

Se ha optado por PyInstaller en modo **carpeta** (`--onedir`), no en fichero único:

| | Carpeta (elegido) | Fichero único |
|---|---|---|
| Arranque | 1–3 s | 10–20 s (se descomprime en cada arranque) |
| Antivirus | Menos falsos positivos | Más falsos positivos |
| Actualizar | Se sustituyen los ficheros cambiados | Se sustituye todo |
| Aspecto | Carpeta con el `.exe` dentro | Un solo fichero |

Se entrega la carpeta comprimida en `.zip`. Es la opción más fiable para un cliente
que va a usar el programa a diario.

Alternativas descartadas: **Nuitka** (compila más rápido pero complica el soporte de
Qt y alarga mucho la compilación) y **cx_Freeze** (menos maduro con PySide6).

## Compilar

En Windows:

```powershell
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1            # o doble clic en compilar_exe.bat
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1 -RunTests  # pasa las pruebas antes
```

El script: busca Python 3.11-3.13 (`py -3.12`, `py -3.13`, `py -3.11`, `python`;
ignora el acceso directo de Microsoft Store), crea `.venv-build`, instala
dependencias, comprueba que la aplicación importa, limpia compilaciones anteriores,
ejecuta PyInstaller, se detiene ante cualquier comando fallido y copia junto al
`.exe` el `.env.example`, `access_profile.example.yaml` y la documentación del
cliente. **Se niega a entregar** si en `dist` aparece un `.env`, un `*.local.yaml`,
una base de datos `*.db` o un `master.key`.

El `.exe` lee un `.env` y `config\access_profile.local.yaml` situados junto a él.
Los scripts están en ASCII puro para funcionar con Windows PowerShell 5.1.

Resultado: `dist\LOT-Bot\LOT-Bot.exe`

## Qué se entrega

```
LOT-Bot\
├── LOT-Bot.exe            ← doble clic
├── _internal\             ← librerías (no tocar)
├── .env.example           ← plantilla de configuración
├── config\
│   └── endpoint_map.example.yaml
└── documentacion\         ← manual del cliente
```

Comprime la carpeta en `LOT-Bot-1.0.0.zip` y entrégala.

## Tamaño

Entre 120 y 220 MB según la plataforma. La mayor parte es Qt. La receta ya descarta:

* Traducciones de Qt salvo español e inglés
* Complementos de Qt que no se usan (QML, multimedia, 3D, web, gráficas…)
* `tkinter`, `unittest`, `pytest` y librerías científicas

No se usa UPX: comprime algo más pero dispara los falsos positivos de los antivirus.

## Firma de código (recomendado)

Sin firma, Windows SmartScreen avisará al cliente la primera vez. Con un certificado
de firma de código:

```powershell
signtool sign /f certificado.pfx /p CONTRASEÑA /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\LOT-Bot\LOT-Bot.exe
```

## Comprobaciones antes de entregar

1. `./scripts/check.sh` (o `pytest`) en verde.
2. Compilar y abrir el `.exe` en una máquina **sin Python instalado**.
3. Comprobar que arranca en MODO DEMO y que las doce pantallas se abren.
4. Comprobar que el `.zip` **no contiene** `.env`, tokens ni `endpoint_map.local.yaml`.

```powershell
# Comprobación rápida de que no se cuela ningún secreto
Get-ChildItem -Recurse dist\LOT-Bot -Include .env,*.local.yaml,*.key
```

## Problemas habituales

| Síntoma | Solución |
|---|---|
| `ModuleNotFoundError` al ejecutar el `.exe` | Añade el módulo a `hiddenimports` en `build/LOT-Bot.spec` |
| Se abre una ventana negra de terminal | `console=False` en el spec (ya está) |
| No aparece el icono | Comprueba que existe `lot_bot/resources/lot_bot.ico` |
| El antivirus lo bloquea | Firma el ejecutable; evita UPX |
| «No se puede escribir la base de datos» | Los datos van a `%LOCALAPPDATA%`, no junto al `.exe`. Revisa permisos de esa carpeta |

## Generar la app de Mac («LOT Bot.app» + `.dmg`)

La misma receta (`build/LOT-Bot.spec`) genera en macOS una aplicación nativa
`LOT Bot.app` (con icono `lot_bot/resources/lot_bot.icns`, `Info.plist` en español y
soporte de modo oscuro / Retina). PyInstaller **no compila de forma cruzada**: la app
de Mac solo se puede generar en un Mac (o en GitHub Actions).

### Opción A — GitHub Actions (sin Mac)

`.github/workflows/build-macos.yml` compila en los Mac de GitHub en cada push a
`main` o `claude/**`, en cada etiqueta `v*` o a mano («Run workflow»). Genera dos
artefactos: `LOT-Bot-macOS-arm64` (chip Apple) y `LOT-Bot-macOS-intel`. Se descargan
en **Actions → App para Mac → última ejecución → Artifacts**.

### Opción B — En un Mac

```bash
./build/build_macos.sh                 # o doble clic en compilar_app_mac.command
./build/build_macos.sh --run-tests     # pasa las pruebas antes
./build/build_macos.sh --skip-install  # no reinstala dependencias
```

Resultado: `dist/LOT Bot.app` y `dist/LOT-Bot-macOS.dmg` (con acceso directo a
Aplicaciones). La app sale para la arquitectura del Mac que compila (arm64 o Intel).

### Firma

Por defecto se firma «ad hoc» (`codesign --sign -`), imprescindible para que abra en
Mac con chip Apple. El cliente tendrá que abrirla la primera vez con clic derecho →
Abrir (ver `docs/cliente/01b-como-instalar-lot-bot-en-mac.md`). Para quitar ese aviso
hace falta una cuenta de Apple Developer:

```bash
MAC_SIGN_IDENTITY="Developer ID Application: Nombre (EQUIPO)" ./build/build_macos.sh
xcrun notarytool submit dist/LOT-Bot-macOS.dmg --apple-id ... --team-id ... --wait
xcrun stapler staple dist/LOT-Bot-macOS.dmg
```

### Diferencias de comportamiento en macOS

* Navegador: busca `Google Chrome.app` y `Microsoft Edge.app` en `/Applications` y
  `~/Applications`; si no, prueba los canales de Playwright.
* Datos: `~/Library/Application Support/LOT Bot/`.
* `.env`: junto a `LOT Bot.app` o en `~/Library/Application Support/LOT Bot/config/`.
* Llavero: la clave maestra va al Llavero de macOS (backend `keyring.backends.macOS`).

### iOS (iPhone / iPad)

No hay versión de iOS: LOT Bot es una app de escritorio Qt que publica controlando
Chrome/Edge con perfiles persistentes (Playwright). iOS no permite lanzar ni
automatizar otro navegador, ni ejecutar el intérprete de Python embebido con estas
dependencias, y Apple no aceptaría la app en la App Store. Sería un proyecto aparte
(p. ej. una app móvil que controle a distancia el LOT Bot del Mac/PC).
