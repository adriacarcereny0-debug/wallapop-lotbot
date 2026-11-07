#!/usr/bin/env bash
# Genera «LOT Bot.app» y «LOT-Bot-macOS.dmg» en un Mac.
#
# Uso:  ./build/build_macos.sh            (instala dependencias y compila)
#       ./build/build_macos.sh --skip-install
#       ./build/build_macos.sh --run-tests
#
# Resultado:
#   dist/LOT Bot.app          -> arrástrala a Aplicaciones
#   dist/LOT-Bot-macOS.dmg    -> para enviársela al cliente
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SKIP_INSTALL=0
RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --skip-install) SKIP_INSTALL=1 ;;
        --run-tests) RUN_TESTS=1 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

if [ "$(uname -s)" != "Darwin" ]; then
    echo "Este script se ejecuta en un Mac (macOS)." >&2
    exit 1
fi

echo "=== LOT Bot · generación de la app para Mac ==="

# 1. Python compatible (PySide6 6.8 publica paquetes para 3.9-3.13)
PYTHON_BIN=""
for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
        case "$version" in
            3.11|3.12|3.13) PYTHON_BIN="$candidate"; break ;;
        esac
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "Instala Python 3.12 desde https://www.python.org/downloads/macos/ y vuelve a probar." >&2
    exit 1
fi
echo "Python: $PYTHON_BIN ($("$PYTHON_BIN" --version))"

# 2. Entorno limpio de compilación
VENV=".venv-build"
if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV"
fi
PY="$VENV/bin/python"

if [ "$SKIP_INSTALL" -eq 0 ]; then
    echo "=== Instalando dependencias ==="
    "$PY" -m pip install --upgrade pip --quiet
    "$PY" -m pip install -r requirements.txt --quiet
    "$PY" -m pip install "pyinstaller>=6.6" --quiet
fi

if [ "$RUN_TESTS" -eq 1 ]; then
    echo "=== Pruebas ==="
    "$PY" -m pip install -r requirements-dev.txt --quiet
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
fi

echo "=== Comprobando importaciones ==="
"$PY" -c "import lot_bot; from lot_bot.app import main; print('OK', lot_bot.__version__)"

# 3. Empaquetar
echo "=== Empaquetando con PyInstaller ==="
rm -rf "dist/LOT Bot.app" "dist/LOT-Bot" dist/LOT-Bot-macOS.dmg
"$PY" -m PyInstaller build/LOT-Bot.spec --noconfirm --clean \
    --workpath build/work --distpath dist

APP="dist/LOT Bot.app"
if [ ! -d "$APP" ]; then
    echo "No se ha generado $APP" >&2
    exit 1
fi

# 4. Firma «ad hoc»: sin ella, los Mac con chip Apple (M1/M2/M3/M4) no abren la app.
#    Con un certificado de Apple Developer: MAC_SIGN_IDENTITY="Developer ID Application: ..."
SIGN_IDENTITY="${MAC_SIGN_IDENTITY:--}"
echo "=== Firmando (${SIGN_IDENTITY}) ==="
codesign --force --deep --sign "$SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict "$APP" && echo "Firma correcta."

# 5. Imagen de disco .dmg con acceso directo a Aplicaciones
echo "=== Creando el .dmg ==="
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicaciones"
hdiutil create -volname "LOT Bot" -srcfolder "$STAGE" -ov -format UDZO dist/LOT-Bot-macOS.dmg >/dev/null
rm -rf "$STAGE"

echo ""
echo "=== Listo ==="
du -sh "$APP" dist/LOT-Bot-macOS.dmg
echo "App:  $PROJECT_ROOT/$APP"
echo "DMG:  $PROJECT_ROOT/dist/LOT-Bot-macOS.dmg"
