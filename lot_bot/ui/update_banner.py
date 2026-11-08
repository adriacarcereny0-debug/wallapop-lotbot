"""Franja «Hay una actualización de LOT Bot» y el proceso de actualizar.

LOT Bot mira solo, al abrirse y cada pocas horas, si hay cambios nuevos en
GitHub. Si los hay, aparece esta franja: «Ver cambios» y «Actualizar». Al
actualizar se reinicia solo. Nunca se actualiza con una cola publicando.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from lot_bot.core.updater import CHECK_EVERY_HOURS, UpdateInfo, restart_lot_bot
from lot_bot.ui.widgets.common import ask_confirmation, info_box, show_error

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application
    from lot_bot.ui.widgets.workers import TaskRunner

logger = logging.getLogger(__name__)


def changes_text(info: UpdateInfo, limit: int = 12) -> str:
    lines = [f"• {c}" for c in info.changes[:limit]]
    if len(info.changes) > limit:
        lines.append(f"• … y {len(info.changes) - limit} más")
    return "\n".join(lines) or "• Mejoras y arreglos."


class UpdateController:
    """Comprobar, actualizar y volver atrás (lo usan la franja y «Acerca de»)."""

    def __init__(self, app: Application, runner: TaskRunner, parent: QWidget) -> None:
        self.app = app
        self.runner = runner
        self.parent = parent
        self.info: UpdateInfo | None = None
        self.listeners: list = []
        self.busy = False

    @property
    def updater(self):
        return getattr(self.app, "updater", None)

    def check(self, *, quiet: bool = True) -> None:
        if self.updater is None or self.busy:
            return
        if not self.updater.supported:
            if not quiet:
                info_box(self.parent, "Actualizaciones", self.updater.unsupported_reason())
            return

        def done(info: UpdateInfo) -> None:
            self.info = info
            for listener in list(self.listeners):
                listener(info)
            if not quiet and not info.available:
                info_box(self.parent, "Actualizaciones", info.message)

        def failed(message: str, _detail: str) -> None:
            logger.info("No se ha podido comprobar si hay actualizaciones: %s", message)
            if not quiet:
                show_error(self.parent, "No se ha podido comprobar si hay actualizaciones.", message)

        self.runner.run(self.updater.check, on_success=done, on_error=failed)

    def _queue_busy(self) -> bool:
        queue = getattr(self.app, "publish_queue", None)
        return bool(queue is not None and queue.is_publishing())

    def update(self) -> None:
        if self.updater is None or self.busy:
            return
        if self._queue_busy():
            show_error(
                self.parent,
                "Ahora no se puede actualizar: hay una cola publicando.",
                "Espera a que termine o páusala en «Publicación automática» y vuelve a pulsar "
                "«Actualizar».",
            )
            return
        info = self.info
        text = "LOT Bot se actualizará y se volverá a abrir solo. Tus cuentas, anuncios, fotos y "
        text += "configuración no se tocan."
        if info is not None and info.available:
            text = f"Novedades:\n{changes_text(info)}\n\n" + text
        if not ask_confirmation(self.parent, "Actualizar LOT Bot", text):
            return
        self.busy = True
        for listener in list(self.listeners):
            listener(None)

        def done(result) -> None:
            self.busy = False
            if not result.ok:
                show_error(self.parent, "No se ha podido actualizar.", result.message)
                for listener in list(self.listeners):
                    listener(self.info)
                return
            self.app.audit.record_success("LOT Bot actualizado", detail=result.message)
            info_box(self.parent, "Actualizado", result.message + "\n\nLOT Bot se va a reiniciar.")
            restart_lot_bot()
            QApplication.quit()

        def failed(message: str, detail: str) -> None:
            self.busy = False
            show_error(self.parent, "No se ha podido actualizar.", message)
            for listener in list(self.listeners):
                listener(self.info)

        self.runner.run(self.updater.apply, on_success=done, on_error=failed)

    def rollback(self) -> None:
        if self.updater is None or not self.updater.previous_version():
            info_box(self.parent, "Versión anterior", "No hay ninguna actualización que deshacer.")
            return
        if self._queue_busy():
            show_error(self.parent, "Ahora no se puede: hay una cola publicando.")
            return
        if not ask_confirmation(
            self.parent,
            "Volver a la versión anterior",
            "LOT Bot volverá a la versión de antes de la última actualización y se reiniciará. "
            "Tus datos no se tocan.",
        ):
            return
        result = self.updater.rollback()
        if not result.ok:
            show_error(self.parent, result.message)
            return
        self.app.audit.record_success("Vuelta a la versión anterior de LOT Bot")
        info_box(self.parent, "Versión anterior", result.message + "\n\nLOT Bot se va a reiniciar.")
        restart_lot_bot()
        QApplication.quit()


class UpdateBanner(QFrame):
    """Franja arriba: «Hay una actualización de LOT Bot» + botones."""

    def __init__(self, controller: UpdateController) -> None:
        super().__init__()
        self.controller = controller
        self.setObjectName("UpdateBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 16, 8)
        layout.setSpacing(10)
        self.label = QLabel()
        self.label.setObjectName("UpdateBannerText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.changes_button = QPushButton("Ver cambios")
        self.changes_button.clicked.connect(self._show_changes)
        layout.addWidget(self.changes_button)
        self.update_button = QPushButton("Actualizar")
        self.update_button.setObjectName("Primary")
        self.update_button.clicked.connect(controller.update)
        layout.addWidget(self.update_button)
        self.setVisible(False)
        controller.listeners.append(self.show_info)

        # Al abrir (con unos segundos de margen) y cada pocas horas. En pruebas
        # y en la demo se desactiva con LOT_BOT_UPDATE_CHECK=0.
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_EVERY_HOURS * 3600 * 1000)
        self.timer.timeout.connect(lambda: controller.check(quiet=True))
        if os.environ.get("LOT_BOT_UPDATE_CHECK", "1") != "0":
            QTimer.singleShot(4000, lambda: controller.check(quiet=True))
            self.timer.start()

    def show_info(self, info: UpdateInfo | None) -> None:
        if info is None:  # actualizando
            self.label.setText("Actualizando LOT Bot… no lo cierres. Se volverá a abrir solo.")
            self.update_button.setEnabled(False)
            self.changes_button.setEnabled(False)
            self.setVisible(True)
            return
        self.update_button.setEnabled(True)
        self.changes_button.setEnabled(True)
        if info.available:
            self.label.setText(
                f"Hay una actualización de LOT Bot ({info.behind} "
                f"{'cambio' if info.behind == 1 else 'cambios'}). Tarda menos de un minuto y tus "
                "datos no se tocan."
            )
        self.setVisible(info.available)

    def _show_changes(self) -> None:
        info = self.controller.info
        if info is not None:
            info_box(self, "Novedades de LOT Bot", changes_text(info, limit=25))
