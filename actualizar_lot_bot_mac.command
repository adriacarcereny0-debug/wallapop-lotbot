#!/usr/bin/env bash
# LOT Bot - actualizar a la última versión de GitHub en Mac (doble clic).
# Normalmente no hace falta: LOT Bot avisa solo y se actualiza con un clic.
# Sirve para la primera vez o si el botón «Actualizar» no funciona.
cd "$(dirname "$0")" || exit 1
if ! command -v git >/dev/null 2>&1; then
    echo "No se encuentra git. Instálalo (xcode-select --install) o usa GitHub Desktop."
    read -r -p "Pulsa Intro para cerrar..." _
    exit 1
fi
echo "Descargando la última versión de LOT Bot..."
git stash push -m "LOT Bot: cambios locales antes de actualizar" >/dev/null 2>&1
# Si existe el canal «estable» en GitHub, se sigue ese; si no, la rama de esta copia.
if git ls-remote --exit-code --heads origin estable >/dev/null 2>&1; then
    git fetch origin estable && git merge --ff-only origin/estable
else
    git pull --ff-only
fi
if [ $? -ne 0 ]; then
    echo ""
    echo "No se ha podido actualizar. Revisa el mensaje de arriba o contacta con soporte."
    read -r -p "Pulsa Intro para cerrar..." _
    exit 1
fi
if [ -x ".venv/bin/python" ]; then
    echo "Comprobando componentes..."
    .venv/bin/python -m pip install --quiet -r requirements.txt
fi
echo ""
echo "LOT Bot está actualizado. Abriéndolo..."
exec bash "./iniciar_lot_bot_mac.command"
