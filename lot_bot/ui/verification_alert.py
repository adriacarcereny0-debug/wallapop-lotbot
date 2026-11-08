"""Aviso cuando Wallapop pide una verificación (CAPTCHA) en una cuenta.

LOT Bot NUNCA resuelve la verificación: la completa la persona. Este aviso
hace que sea imposible no enterarse:

* franja de color visible en TODAS las pantallas de LOT Bot, con un botón
  para volver a poner delante la ventana de Chrome de esa cuenta;
* sonido de aviso (y se repite cada pocos minutos mientras siga pendiente);
* notificación de Windows y el icono de LOT Bot parpadea en la barra de tareas.

En cuanto la verificación desaparece, la publicación sigue sola y la franja
se quita (con una notificación de «todo sigue»).
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

#: Cada cuánto se repite el sonido mientras la verificación siga pendiente.
REPEAT_SOUND_S = 120


def play_alert_sound() -> None:
    """Sonido de aviso del sistema (en Windows, el de «exclamación»)."""
    try:
        if sys.platform == "win32":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            QApplication.beep()
    except Exception:  # un aviso nunca debe romper nada
        logger.debug("No se ha podido reproducir el sonido de aviso", exc_info=True)


def banner_text(pending: list[dict[str, Any]]) -> str:
    names = ", ".join(f"«{p['cuenta']}»" for p in pending)
    plural = len(pending) > 1
    text = (
        f"⚠  Wallapop pide una verificación en {'las cuentas' if plural else 'la cuenta'} "
        f"{names}. Complétala en la ventana de Chrome que se ha puesto delante. "
        "En cuanto desaparezca, LOT Bot sigue solo (no hace falta pulsar nada más)."
    )
    if any(p["aplazada"] for p in pending):
        text += " Mientras tanto se sigue publicando en las demás cuentas."
    return text


class VerificationAlert(QFrame):
    """Franja de aviso + sonido + notificación de Windows."""

    def __init__(self, app: Application, window: QWidget, icon: QIcon) -> None:
        super().__init__()
        self.app = app
        self.window = window
        self.setObjectName("VerificationBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 16, 10)
        layout.setSpacing(12)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setObjectName("VerificationBannerText")
        layout.addWidget(self.label, 1)
        self.show_button = QPushButton("Mostrar la ventana de Chrome")
        self.show_button.setObjectName("Primary")
        self.show_button.clicked.connect(self.show_browser_windows)
        layout.addWidget(self.show_button)
        self.setVisible(False)

        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, window)
            self.tray.setToolTip("LOT Bot")
            self.tray.messageClicked.connect(self._bring_lot_bot)
            self.tray.activated.connect(lambda _reason: self._bring_lot_bot())
            self.tray.show()

        self._known: set[str] = set()
        self._last_sound: datetime | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    # ------------------------------------------------------------------
    def pending(self) -> list[dict[str, Any]]:
        queue = getattr(self.app, "publish_queue", None)
        if queue is None or not hasattr(queue, "pending_verifications"):
            return []
        try:
            return queue.pending_verifications()
        except Exception:
            logger.debug("No se han podido leer las verificaciones", exc_info=True)
            return []

    def check(self) -> None:
        pending = self.pending()
        refs = {p["cuenta_ref"] for p in pending}
        new = refs - self._known
        solved = self._known - refs
        self._known = refs
        if pending:
            self.label.setText(banner_text(pending))
            self.setVisible(True)
        else:
            self.setVisible(False)
        now = datetime.now()
        if new:
            names = ", ".join(p["cuenta"] for p in pending if p["cuenta_ref"] in new)
            self._alert(
                "Wallapop pide una verificación",
                f"Cuenta {names}: complétala en la ventana de Chrome. "
                "LOT Bot seguirá solo en cuanto desaparezca.",
            )
            self._last_sound = now
        elif pending and self._last_sound is not None and (
            (now - self._last_sound).total_seconds() >= REPEAT_SOUND_S
        ):
            play_alert_sound()  # sigue pendiente: recordatorio
            self._last_sound = now
        if solved and not pending:
            self._last_sound = None
            self._notify("Verificación completada", "La publicación automática sigue sola.")

    def _alert(self, title: str, message: str) -> None:
        play_alert_sound()
        self._notify(title, message, warning=True)
        try:
            QApplication.alert(self.window, 0)  # parpadea en la barra de tareas
        except Exception:
            logger.debug("No se ha podido hacer parpadear la ventana", exc_info=True)

    def _notify(self, title: str, message: str, *, warning: bool = False) -> None:
        if self.tray is None:
            return
        icon = (
            QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
        )
        try:
            self.tray.showMessage(title, message, icon, 15000 if warning else 5000)
        except Exception:
            logger.debug("No se ha podido mostrar la notificación", exc_info=True)

    def _bring_lot_bot(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def show_browser_windows(self) -> None:
        """Vuelve a poner delante la ventana de Chrome de cada cuenta pendiente
        (en segundo plano: no congela LOT Bot)."""
        queue = getattr(self.app, "publish_queue", None)
        show = getattr(queue, "show_verification_window", None)
        if not callable(show):
            return
        refs = [p["cuenta_ref"] for p in self.pending()]

        def run() -> None:
            for ref in refs:
                try:
                    show(ref)
                except Exception:
                    logger.debug("No se ha podido mostrar la ventana de %s", ref, exc_info=True)

        threading.Thread(target=run, name="lotbot-mostrar-ventana", daemon=True).start()
