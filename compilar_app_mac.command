#!/usr/bin/env bash
# LOT Bot - genera «dist/LOT Bot.app» y «dist/LOT-Bot-macOS.dmg» con doble clic.
cd "$(dirname "$0")" || exit 1
bash build/build_macos.sh "$@"
status=$?
echo ""
read -r -p "Pulsa Intro para cerrar..." _
exit $status
