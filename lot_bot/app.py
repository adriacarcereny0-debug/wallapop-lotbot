"""Punto de entrada de LOT Bot."""

from __future__ import annotations

import logging
import sys
import traceback

from lot_bot import APP_NAME, ORG_NAME, __version__

logger = logging.getLogger(__name__)


def _offer_crash_report(box, detail: str) -> None:
    """Botón «Crear informe para soporte» en las ventanas de error grave."""
    from PySide6.QtWidgets import QMessageBox

    button = box.addButton("Crear informe para soporte", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is not button:
        return
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from lot_bot.core.support_report import build_crash_report

        path = build_crash_report(detail)
        done = QMessageBox()
        done.setWindowTitle(f"{APP_NAME} · informe creado")
        done.setText(
            f"Se ha guardado en:\n\n{path}\n\nEnvíaselo a soporte por WhatsApp o email. "
            "No lleva contraseñas ni claves."
        )
        done.exec()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    except Exception:  # pragma: no cover - si ni esto funciona, al menos no se cuelga
        logger.exception("No se ha podido crear el informe de arranque")


def _install_exception_hook() -> None:
    """Muestra un mensaje entendible si algo falla de forma inesperada."""

    def hook(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Error no controlado", exc_info=(exc_type, exc_value, exc_traceback)
        )
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                box = QMessageBox()
                box.setWindowTitle(f"{APP_NAME} · error inesperado")
                box.setIcon(QMessageBox.Icon.Critical)
                box.setText(
                    "Se ha producido un error inesperado.\n"
                    "El detalle técnico se ha guardado en los registros."
                )
                detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                box.setDetailedText(detail)
                _offer_crash_report(box, detail)
        except Exception:  # pragma: no cover
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    """Arranca la aplicación de escritorio."""
    from PySide6.QtCore import QLocale, Qt
    from PySide6.QtWidgets import QApplication

    from lot_bot.bootstrap import create_application, seed_demo_catalog
    from lot_bot.ui.main_window import MainWindow
    from lot_bot.ui.theme import stylesheet

    # Números y precios con formato español (11,44 €) en toda la interfaz.
    QLocale.setDefault(QLocale(QLocale.Language.Spanish, QLocale.Country.Spain))
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    qt_app = QApplication(argv if argv is not None else sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationVersion(__version__)
    qt_app.setOrganizationName(ORG_NAME)
    # «Fusion»: el tema se ve igual en todos los Windows (el estilo nativo
    # ignora parte de la hoja de estilos: flechas, casillas, desplegables).
    qt_app.setStyle("Fusion")
    qt_app.setStyleSheet(stylesheet())

    _install_exception_hook()

    try:
        app = create_application()
    except Exception as exc:
        logger.critical("No se ha podido iniciar LOT Bot", exc_info=True)
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox()
        box.setWindowTitle(f"{APP_NAME} · no se ha podido iniciar")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(
            f"LOT Bot no ha podido arrancar:\n\n{exc}\n\nTus datos no se han tocado. Pulsa «Crear "
            "informe para soporte» y envíanoslo para que te ayudemos."
        )
        detail = traceback.format_exc()
        box.setDetailedText(detail)
        _offer_crash_report(box, detail)
        return 1

    if app.demo_mode:
        seed_demo_catalog(app)

    # Licencia: con Wallapop real y sin licencia activa, primero la pantalla de
    # activación. Nunca impide abrir el programa («Continuar sin licencia»).
    from lot_bot.ui.license import LicenseDialog, needs_license

    if needs_license(app):
        LicenseDialog(app.license).exec()

    window = MainWindow(app)
    window.show()
    # Guía de primeros pasos (sale sola mientras falte algo por hacer).
    from PySide6.QtCore import QTimer

    QTimer.singleShot(900, window.maybe_show_onboarding)
    logger.info("Ventana principal abierta.")
    return qt_app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
