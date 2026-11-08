"""Botón «Enviar informe a soporte»: pregunta qué ha pasado, crea el .zip en el
Escritorio y abre la carpeta para enviarlo por WhatsApp o email."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog

from lot_bot.ui.widgets.common import info_box


def send_support_report(view) -> None:
    from lot_bot.core.support_report import build_report

    description, accepted = QInputDialog.getMultiLineText(
        view,
        "Enviar informe a soporte",
        "Cuenta en pocas palabras qué ha pasado (qué estabas haciendo y qué has visto).\n"
        "El informe no lleva contraseñas, cookies ni claves.",
    )
    if not accepted:
        return

    def done(path) -> None:
        info_box(
            view,
            "Informe creado",
            f"Se ha guardado en:\n\n{path}\n\nEnvíaselo a soporte por WhatsApp o email. "
            "Ahora se abre la carpeta donde está.",
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    view.run_task(build_report, view.app, description, on_success=done)
