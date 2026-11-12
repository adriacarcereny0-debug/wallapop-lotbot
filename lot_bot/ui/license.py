"""Pantallas de la licencia: activación, franja de aviso y tarjeta en Configuración.

* `LicenseDialog`: se abre al arrancar si se usa Wallapop real y la licencia
  no está activa (y desde Configuración → Licencia). Nunca impide abrir LOT
  Bot: «Continuar sin licencia» abre el programa con todos los datos, solo que
  sin publicar ni cambiar nada en Wallapop real.
* `LicenseBanner`: franja arriba en todas las pantallas cuando la licencia no
  está activa, cuando falta poco para que caduque o cuando lleva tiempo sin
  poder comprobarla (sin conexión).
* `LicensePanel`: la pestaña «Licencia» de Configuración.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lot_bot import APP_NAME
from lot_bot.licensing.config import PURCHASE_URL
from lot_bot.licensing.manager import LicenseManager, LicenseState, LicenseStatus, normalize_key
from lot_bot.ui import theme
from lot_bot.ui.widgets.common import Card, SectionTitle, ask_confirmation, info_box, show_error
from lot_bot.ui.widgets.workers import TaskRunner

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

#: Avisar cuando falte menos que esto para que caduque la licencia.
EXPIRY_WARNING_DAYS = 3
#: Avisar sin conexión cuando al pase le quede menos que esto.
OFFLINE_WARNING_HOURS = 24


def _fmt(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")


def needs_license(app: Application) -> bool:
    """¿Hay que pedir licencia al abrir? Solo con Wallapop real y si no está activa."""
    manager = getattr(app, "license", None)
    if manager is None or app.demo_mode:
        return False
    return not manager.status().allowed


class LicenseSignals(QObject):
    """Lleva los avisos del hilo de la licencia a la interfaz."""

    changed = Signal(object)

    def __init__(self, manager: LicenseManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        manager.listeners.append(self._emit)
        self.destroyed.connect(lambda *_: self._detach())

    def _emit(self, status: LicenseStatus) -> None:
        try:
            self.changed.emit(status)
        except RuntimeError:  # objeto ya destruido
            self._detach()

    def _detach(self) -> None:
        try:
            self.manager.listeners.remove(self._emit)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
class LicenseDialog(QDialog):
    """Pantalla de activación."""

    def __init__(
        self,
        manager: LicenseManager,
        parent: QWidget | None = None,
        *,
        demo_hint: bool = True,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.runner = TaskRunner(1)
        self.activated = False
        self.setWindowTitle(f"{APP_NAME} · Activar licencia")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setObjectName("LicenseDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        title = QLabel("Activa tu licencia de LOT Bot")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Escribe la clave que te llegó al contratar (o al pedir la prueba gratis de 24 h). "
            "Se vincula a este ordenador."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.state_label = QLabel()
        self.state_label.setObjectName("LicenseState")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)

        key_title = QLabel("Clave de licencia")
        key_title.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-weight: 600;")
        layout.addWidget(key_title)
        self.key_input = QLineEdit()
        self.key_input.setObjectName("LicenseKey")
        self.key_input.setPlaceholderText("LOTB-XXXX-XXXX-XXXX")
        self.key_input.setMaxLength(24)
        self.key_input.setMinimumHeight(42)
        self.key_input.setStyleSheet(
            "font-family: 'Consolas', 'Menlo', monospace; font-size: 17px; letter-spacing: 1px;"
        )
        self.key_input.textEdited.connect(self._format_key)
        self.key_input.returnPressed.connect(self._activate)
        layout.addWidget(self.key_input)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        layout.addWidget(self.message)

        self.activate_button = QPushButton("Activar licencia")
        self.activate_button.setObjectName("Primary")
        self.activate_button.setMinimumHeight(40)
        self.activate_button.clicked.connect(self._activate)
        layout.addWidget(self.activate_button)

        buy = QLabel(
            f'¿No tienes licencia? <a href="{PURCHASE_URL}" style="color:{theme.ACCENT}">'
            "Prueba 24 h gratis o elige un plan</a>"
        )
        buy.setOpenExternalLinks(True)
        buy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(buy)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        layout.addWidget(line)

        device = manager.device
        footer = QLabel(
            f"Este ordenador: {device.name} · {device.os}\n"
            "Tus cuentas, anuncios, fotos y configuración se quedan en este ordenador y no se "
            "borran nunca, tengas licencia o no."
        )
        footer.setWordWrap(True)
        footer.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        layout.addWidget(footer)

        row = QHBoxLayout()
        row.addStretch(1)
        self.skip_button = QPushButton(
            "Continuar sin licencia" if demo_hint else "Cerrar"
        )
        self.skip_button.setToolTip(
            "LOT Bot se abre con todos tus datos, pero no publica ni cambia nada en Wallapop "
            "real hasta que actives la licencia. El modo DEMO es gratis."
        )
        self.skip_button.clicked.connect(self.reject)
        row.addWidget(self.skip_button)
        layout.addLayout(row)

        stored = manager.stored_key()
        if stored:
            self.key_input.setText(stored)
        self._show_status(manager.status())

    # ------------------------------------------------------------------
    def _format_key(self, text: str) -> None:
        formatted = normalize_key(text)
        if formatted != text and len(formatted) <= 19:
            self.key_input.setText(formatted)

    def _show_status(self, status: LicenseStatus) -> None:
        color = {
            LicenseState.ACTIVE: theme.SUCCESS,
            LicenseState.BLOCKED: theme.DANGER,
        }.get(status.state, theme.TEXT_MUTED)
        text = self.manager.describe(status)
        self.state_label.setText(text)
        self.state_label.setStyleSheet(
            f"color: {color}; background: {theme.CARD}; border: 1px solid {theme.BORDER};"
            "border-radius: 8px; padding: 10px 12px;"
        )
        self.state_label.setVisible(bool(text))
        self._fit()

    def _fit(self) -> None:
        """Con textos de varias líneas, que nada quede cortado."""
        self.layout().activate()
        self.resize(self.width(), max(self.height(), self.sizeHint().height()))

    def _say(self, text: str, *, error: bool) -> None:
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {theme.DANGER if error else theme.SUCCESS};")
        self.message.setVisible(True)
        self._fit()

    def _activate(self) -> None:
        if not self.activate_button.isEnabled():
            return
        key = self.key_input.text()
        self.activate_button.setEnabled(False)
        self.activate_button.setText("Comprobando…")
        self._say("Conectando con el servidor de licencias…", error=False)

        def done(result: Any) -> None:
            self.activate_button.setEnabled(True)
            self.activate_button.setText("Activar licencia")
            self._show_status(self.manager.status())
            if result.ok:
                self.activated = True
                self._say("¡Listo! LOT Bot ya puede publicar en Wallapop desde este ordenador.", error=False)
                QTimer.singleShot(900, self.accept)
            else:
                self._say(result.message, error=True)

        def failed(message: str, _detail: str) -> None:
            self.activate_button.setEnabled(True)
            self.activate_button.setText("Activar licencia")
            self._say(f"No se ha podido activar: {message}", error=True)

        self.runner.run(self.manager.activate, key, on_success=done, on_error=failed)


# ---------------------------------------------------------------------------
def banner_text(status: LicenseStatus, *, demo: bool, now: datetime | None = None) -> str:
    """Texto de la franja ('' = no se muestra)."""
    if demo or status.state is LicenseState.DISABLED:
        return ""
    now = now or datetime.now(UTC)
    if not status.allowed:
        lead = "Sin licencia activa" if status.state is LicenseState.NONE else "Licencia no activa"
        return (
            f"{lead}: LOT Bot no publica ni cambia nada en Wallapop. Tus datos siguen aquí. "
            + (status.message if status.state is LicenseState.BLOCKED else "")
        ).strip()
    if status.license_expires_at is not None:
        left = status.license_expires_at - now
        if left.total_seconds() < EXPIRY_WARNING_DAYS * 86400:
            what = "La prueba gratis termina" if status.is_trial else "Tu licencia caduca"
            return f"{what} el {_fmt(status.license_expires_at)}. Renuévala para no parar las colas."
    if status.offline and status.lease_expires_at is not None:
        left = status.lease_expires_at - now
        if left.total_seconds() < OFFLINE_WARNING_HOURS * 3600:
            return (
                "LOT Bot no puede comprobar la licencia (sin conexión). Conéctate a Internet antes "
                f"del {_fmt(status.lease_expires_at)} para no parar las colas."
            )
    return ""


class LicenseBanner(QFrame):
    """Franja arriba con el estado de la licencia (solo si hay algo que decir)."""

    def __init__(self, app: Application, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.setObjectName("LicenseBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 16, 8)
        layout.setSpacing(10)
        self.label = QLabel()
        self.label.setObjectName("LicenseBannerText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.buy_button = QPushButton("Renovar / comprar")
        self.buy_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PURCHASE_URL)))
        layout.addWidget(self.buy_button)
        self.activate_button = QPushButton("Activar licencia")
        self.activate_button.setObjectName("Primary")
        self.activate_button.clicked.connect(self.open_dialog)
        layout.addWidget(self.activate_button)
        self.setVisible(False)

        manager = getattr(app, "license", None)
        if manager is not None:
            self.signals = LicenseSignals(manager, self)
            self.signals.changed.connect(lambda _status: self.refresh())
            # La caducidad y el «sin conexión» dependen de la hora: se mira cada minuto.
            self.timer = QTimer(self)
            self.timer.setInterval(60_000)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        manager = getattr(self.app, "license", None)
        if manager is None:
            self.setVisible(False)
            return
        status = manager.status()
        text = banner_text(status, demo=self.app.demo_mode)
        self.label.setText(text)
        blocked = not status.allowed
        self.activate_button.setVisible(blocked)
        self.setProperty("blocked", blocked)
        self.setStyleSheet(
            "QFrame#LicenseBanner { background: %s; border-bottom: 1px solid %s; }"
            "QLabel#LicenseBannerText { color: %s; font-weight: 600; background: transparent; }"
            % (("#2a1716", "#4d2523", "#f6c4c0") if blocked else ("#2a2215", "#4a3818", "#f2d9ae"))
        )
        self.setVisible(bool(text))

    def open_dialog(self) -> None:
        manager = getattr(self.app, "license", None)
        if manager is None:
            return
        LicenseDialog(manager, self.window(), demo_hint=False).exec()
        self.refresh()


# ---------------------------------------------------------------------------
class LicensePanel(QWidget):
    """Pestaña «Licencia» de Configuración."""

    def __init__(self, app: Application, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.runner = TaskRunner(1)
        layout = QVBoxLayout(self)

        card = Card()
        card.add(SectionTitle("Licencia de este ordenador"))
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.state_label.setStyleSheet("font-weight: 600;")
        card.add(self.state_label)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        card.add(self.details)

        row = QHBoxLayout()
        self.activate_button = QPushButton("Activar o cambiar clave")
        self.activate_button.setObjectName("Primary")
        self.activate_button.clicked.connect(self._open_dialog)
        row.addWidget(self.activate_button)
        self.check_button = QPushButton("Comprobar ahora")
        self.check_button.clicked.connect(self._check_now)
        row.addWidget(self.check_button)
        buy = QPushButton("Renovar / comprar")
        buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PURCHASE_URL)))
        row.addWidget(buy)
        row.addStretch(1)
        self.deactivate_button = QPushButton("Desvincular este ordenador")
        self.deactivate_button.clicked.connect(self._deactivate)
        row.addWidget(self.deactivate_button)
        card.body.addLayout(row)
        layout.addWidget(card)

        how = Card()
        how.add(SectionTitle("Cómo funciona"))
        text = QLabel(
            "• La licencia se vincula a este ordenador (plan mensual: 1 ordenador; anual: 2).\n"
            "• LOT Bot la comprueba solo cada 4-6 horas. Sin Internet sigue funcionando hasta "
            "3 días.\n"
            "• Si caduca o se suspende, la cola termina el anuncio que esté publicando y se "
            "pausa; al renovarla sigue sola.\n"
            "• Tus cuentas, anuncios, fotos y configuración no se borran nunca.\n"
            "• El modo DEMO es gratis y no necesita licencia.\n"
            "• Para pasar la licencia a otro ordenador, pulsa «Desvincular este ordenador» aquí "
            "y actívala en el otro."
        )
        text.setWordWrap(True)
        how.add(text)
        layout.addWidget(how)
        layout.addStretch(1)

        manager = getattr(app, "license", None)
        if manager is not None:
            self.signals = LicenseSignals(manager, self)
            self.signals.changed.connect(lambda _status: self.refresh())
        self.refresh()

    @property
    def manager(self) -> LicenseManager | None:
        return getattr(self.app, "license", None)

    def refresh(self) -> None:
        manager = self.manager
        if manager is None or not manager.enforced:
            self.state_label.setText("Esta versión de LOT Bot no necesita licencia.")
            self.state_label.setStyleSheet(f"font-weight: 600; color: {theme.TEXT_MUTED};")
            self.details.setText("")
            for button in (self.activate_button, self.check_button, self.deactivate_button):
                button.setEnabled(False)
            return
        status = manager.status()
        color = {
            LicenseState.ACTIVE: theme.SUCCESS,
            LicenseState.BLOCKED: theme.DANGER,
        }.get(status.state, theme.WARNING)
        self.state_label.setText(manager.describe(status))
        self.state_label.setStyleSheet(f"font-weight: 600; color: {color};")
        device = manager.device
        lines = []
        if status.key_masked:
            lines.append(f"Clave: {status.key_masked}")
        if status.plan or status.kind:
            plan = "Prueba gratis" if status.is_trial else (status.plan or status.kind).capitalize()
            if status.seats:
                plan += f" · hasta {status.seats} " + ("ordenador" if status.seats == 1 else "ordenadores")
            lines.append(f"Plan: {plan}")
        lines.append(f"Caduca: {_fmt(status.license_expires_at)}" if status.license_expires_at else "")
        if status.lease_expires_at:
            lines.append(f"Funciona sin conexión hasta: {_fmt(status.lease_expires_at)}")
        lines.append(f"Última comprobación: {_fmt(status.last_success)}" + (" (ahora sin conexión)" if status.offline else ""))
        lines.append(f"Este ordenador: {device.name} · {device.os}")
        self.details.setText("\n".join(line for line in lines if line))
        has_key = bool(status.key_masked)
        self.activate_button.setEnabled(True)
        self.check_button.setEnabled(has_key)
        self.deactivate_button.setEnabled(has_key)

    def _open_dialog(self) -> None:
        if self.manager is None:
            return
        LicenseDialog(self.manager, self.window(), demo_hint=False).exec()
        self.refresh()

    def _check_now(self) -> None:
        manager = self.manager
        if manager is None:
            return
        self.check_button.setEnabled(False)
        self.check_button.setText("Comprobando…")

        def finish(*_args: Any) -> None:
            self.check_button.setText("Comprobar ahora")
            self.refresh()

        def failed(message: str, _detail: str) -> None:
            finish()
            show_error(self, "No se ha podido comprobar la licencia.", message)

        self.runner.run(manager.refresh, on_success=finish, on_error=failed)

    def _deactivate(self) -> None:
        manager = self.manager
        if manager is None:
            return
        queue = getattr(self.app, "publish_queue", None)
        if queue is not None and queue.is_publishing():
            show_error(
                self,
                "Ahora no se puede: hay una cola publicando.",
                "Espera a que termine o páusala y vuelve a probar.",
            )
            return
        if not ask_confirmation(
            self,
            "Desvincular este ordenador",
            "La licencia dejará de funcionar en este ordenador y podrás activarla en otro. "
            "Tus datos no se tocan. ¿Seguir?",
            destructive=True,
        ):
            return
        self.deactivate_button.setEnabled(False)

        def done(result: Any) -> None:
            self.refresh()
            if result.ok:
                info_box(self, "Licencia", result.message)
            else:
                show_error(self, "No se ha podido desvincular.", result.message)

        def failed(message: str, _detail: str) -> None:
            self.refresh()
            show_error(self, "No se ha podido desvincular.", message)

        self.runner.run(manager.deactivate, on_success=done, on_error=failed)
