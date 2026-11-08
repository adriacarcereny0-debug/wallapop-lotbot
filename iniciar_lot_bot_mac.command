#!/usr/bin/env bash
# LOT Bot - arranque con doble clic en Mac (desarrollo).
# La primera vez prepara el entorno; después abre la aplicación.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "Preparando LOT Bot por primera vez. Puede tardar unos minutos..."
    if ! bash scripts/install_dev.sh; then
        echo ""
        echo "No se ha podido preparar el entorno. Revisa el mensaje de arriba."
        read -r -p "Pulsa Intro para cerrar..." _
        exit 1
    fi
fi

# Si falta algún componente (p. ej. tras actualizar), se instala solo.
if ! .venv/bin/python -c "import playwright, PySide6" >/dev/null 2>&1; then
    echo "Instalando los componentes que faltan. Puede tardar unos minutos..."
    if ! .venv/bin/python -m pip install -r requirements.txt; then
        echo ""
        echo "No se han podido instalar los componentes. Revisa el mensaje de arriba."
        read -r -p "Pulsa Intro para cerrar..." _
        exit 1
    fi
fi

nohup .venv/bin/python run_lot_bot.py >/dev/null 2>&1 &
echo "LOT Bot se está abriendo. Ya puedes cerrar esta ventana."
exit 0
