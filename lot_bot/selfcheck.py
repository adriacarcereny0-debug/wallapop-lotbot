"""Autoprueba de LOT Bot: comprueba que el programa empaquetado funciona de verdad.

Uso:
    LOT-Bot --autoprueba            (ejecutable de Windows o «LOT Bot.app» de Mac)
    python run_lot_bot.py --autoprueba

Comprueba, sin tocar Wallapop ni los datos del usuario:

1. Que todos los módulos de LOT Bot cargan (nada se quedó fuera del paquete).
2. Que la interfaz Qt arranca.
3. Que la base de datos funciona.
4. Que el llavero del sistema está disponible.
5. Que Playwright abre Chrome/Edge (o su Chromium) desde DENTRO del paquete,
   carga una página y la lee: es exactamente lo que hace el bot al publicar.

Imprime una línea por comprobación y termina con código 0 si todo va bien.
Se usa en la compilación automática antes de publicar la app para clientes.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path

ARG = "--autoprueba"


def _check_imports() -> str:
    import importlib
    import pkgutil

    import lot_bot

    count = 0
    for module in pkgutil.walk_packages(lot_bot.__path__, "lot_bot."):
        if ".tests" in module.name:
            continue
        importlib.import_module(module.name)
        count += 1
    return f"{count} módulos cargados (versión {lot_bot.__version__})"


def _check_qt() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from lot_bot.ui.theme import stylesheet

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setStyleSheet(stylesheet())
    label = QLabel("LOT Bot")
    label.show()
    app.processEvents()
    label.close()
    return f"Qt {app.platformName()}"


def _check_database(workdir: Path) -> str:
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{workdir / 'autoprueba.db'}")
    with engine.connect() as connection:
        value = connection.execute(text("select 41 + 1")).scalar_one()
    engine.dispose()
    if value != 42:
        raise RuntimeError("SQLite devolvió un resultado incorrecto")
    return "SQLite correcto"


def _check_keyring() -> str:
    import keyring

    backend = keyring.get_keyring()
    name = f"{type(backend).__module__}.{type(backend).__name__}"
    if "fail" in name.lower() or "null" in name.lower():
        # En Mac y Windows el llavero tiene que estar SIEMPRE (va dentro del paquete).
        # En Linux sin escritorio es normal no tenerlo: LOT Bot usa un fichero.
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            raise RuntimeError(f"sin llavero del sistema ({name})")
        return f"{name} (sin llavero en este sistema: se usa fichero local)"
    return name


def _check_browser(workdir: Path) -> str:
    from lot_bot.wallapop.browser.driver import PlaywrightLauncher

    html = "<html><head><title>autoprueba</title></head><body>LOT Bot listo</body></html>"
    page_file = workdir / "autoprueba.html"
    page_file.write_text(html, encoding="utf-8")
    launcher = PlaywrightLauncher(default_timeout_ms=30000)
    with launcher.open(
        workdir / "perfil",
        visible=False,
        channels=["chrome", "msedge", "chromium"],
        locale="es-ES",
    ) as page:
        page.goto(page_file.as_uri())
        body = page.body_text()
        info = getattr(page, "_launch_info", "") or ""
    if "LOT Bot listo" not in body:
        raise RuntimeError(f"la página no se ha leído bien: {body[:80]!r}")
    browser = info.split(";")[0].replace("navegador=", "") if info else "navegador"
    return f"{browser} abierto y controlado por el bot"


def run() -> int:
    """Ejecuta todas las comprobaciones. 0 = todo correcto."""
    print("=== LOT Bot · autoprueba ===", flush=True)
    print(f"Sistema: {sys.platform} · Python {sys.version.split()[0]}", flush=True)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="lotbot-autoprueba-") as tmp:
        workdir = Path(tmp)
        # Datos aislados: la autoprueba nunca toca la base de datos del usuario.
        os.environ["LOT_BOT_DATA_DIR"] = str(workdir / "datos")
        checks: list[tuple[str, Callable[[], str]]] = [
            ("Módulos", _check_imports),
            ("Interfaz", _check_qt),
            ("Base de datos", lambda: _check_database(workdir)),
            ("Llavero", _check_keyring),
            ("Navegador", lambda: _check_browser(workdir)),
        ]
        for name, check in checks:
            started = time.monotonic()
            try:
                detail = check()
                print(f"[OK]    {name}: {detail} ({time.monotonic() - started:.1f}s)", flush=True)
            except Exception as exc:  # noqa: BLE001 - se informa de cualquier fallo
                failures += 1
                print(f"[FALLO] {name}: {exc}", flush=True)
                traceback.print_exc()
    print("=== Resultado: " + ("TODO CORRECTO ===" if not failures else f"{failures} FALLO(S) ==="))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(run())
