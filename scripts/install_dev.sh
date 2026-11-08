#!/usr/bin/env bash
# Prepara el entorno de desarrollo de LOT Bot en Linux/macOS.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== LOT Bot · entorno de desarrollo ==="

# Python 3.11 o superior. En Mac, el «python3» que trae el sistema es el 3.9
# (no vale): se busca primero el instalado desde python.org o Homebrew.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "" >&2
    echo "Falta Python 3.11 o superior." >&2
    if [ "$(uname)" = "Darwin" ]; then
        echo "Descárgalo de https://www.python.org/downloads/macos/ (botón «Download Python 3.12…»)," >&2
        echo "instálalo con doble clic y vuelve a abrir iniciar_lot_bot_mac.command." >&2
        open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
    fi
    exit 1
fi

VERSION=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "Python detectado: $VERSION ($PYTHON)"

# Un entorno creado antes con un Python viejo no sirve: se rehace.
if [ -x ".venv/bin/python" ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "El entorno anterior usaba un Python demasiado antiguo: se vuelve a crear."
    rm -rf .venv
fi

if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    "$PYTHON" -m venv .venv
fi

echo "Instalando dependencias..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements-dev.txt

if [ ! -f ".env" ]; then
    echo "Creando .env a partir de .env.example..."
    cp .env.example .env
    echo "Edita .env con tus credenciales. Sin ellas, LOT Bot funciona en MODO DEMO."
fi

cat <<'MSG'

=== Listo ===
Arrancar la aplicación:   .venv/bin/python run_lot_bot.py
Ejecutar las pruebas:     .venv/bin/python -m pytest
Comprobar el empaquetado: ./build/build.sh

Nota: en Linux, Qt necesita algunas librerías del sistema:
  sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1
MSG
