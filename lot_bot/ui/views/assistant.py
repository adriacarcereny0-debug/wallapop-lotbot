"""Asistente IA: el chat principal de LOT Bot.

Flujo: el usuario escribe una orden -> el agente la interpreta -> si la accion
modifica informacion, aparece el panel [Cancelar] [Confirmar] y nada se ejecuta
hasta que el usuario decide.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lot_bot.ai.agent import AgentResponse
from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import ConfirmationPanel

EXAMPLES = [
    "Prepara el anuncio de canapé",
    "Publica el anuncio de canapé",
    "Empieza a subir anuncios cada 60 segundos",
    "¿Cómo va la cola?",
    "Estadísticas",
    "¿Qué anuncios tienen más visualizaciones?",
]


#: Ancho máximo de la conversación: más ancho cuesta leer.
CHAT_MAX_WIDTH = 860
#: Una burbuja ocupa como mucho esta parte del ancho del chat.
BUBBLE_RATIO = 0.78
BUBBLE_PADDING = (14, 10)

#: Colores de cada tipo de mensaje: (fondo, borde, texto).
BUBBLE_COLORS = {
    "usuario": (theme.ACCENT_SOFT, "#4a3818", theme.TEXT),
    "asistente": (theme.CARD, theme.BORDER, theme.TEXT),
    "error": ("#2a1418", "#4a2328", theme.DANGER),
}


def _logo(size: int) -> QPixmap:
    from lot_bot.ui.main_window import _logo_pixmap

    return _logo_pixmap(size)


class ChatBubble(QWidget):
    """Un mensaje del chat: tuyo a la derecha, de LOT Bot a la izquierda con
    su icono, y las acciones que hace como una línea pequeña."""

    def __init__(self, role: str, text: str, tool_name: str | None = None) -> None:
        super().__init__()
        self.role = role
        self.text = text
        self.bubble: QFrame | None = None
        self.body: QLabel | None = None
        now = datetime.now()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        if role == "herramienta":
            # Acción que ha hecho LOT Bot: una línea discreta, sin repetir el
            # resultado (LOT Bot lo explica justo después).
            row.addSpacing(38)
            chip = QLabel(f"✓  {tool_name or 'Acción hecha'}")
            chip.setObjectName("ChatAction")
            chip.setToolTip(text)
            row.addWidget(chip)
            row.addStretch(1)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            return

        background, border, color = BUBBLE_COLORS.get(role, BUBBLE_COLORS["asistente"])
        column = QVBoxLayout()
        column.setSpacing(3)
        self.bubble = QFrame()
        self.bubble.setObjectName("ChatBubble")
        mine = role == "usuario"
        radius = "14px 14px 4px 14px" if mine else "4px 14px 14px 14px"
        tl, tr, br, bl = radius.split()
        self.bubble.setStyleSheet(
            f"QFrame#ChatBubble {{ background: {background}; border: 1px solid {border};"
            f" border-top-left-radius: {tl}; border-top-right-radius: {tr};"
            f" border-bottom-right-radius: {br}; border-bottom-left-radius: {bl}; }}"
        )
        inner = QVBoxLayout(self.bubble)
        inner.setContentsMargins(BUBBLE_PADDING[0], BUBBLE_PADDING[1], BUBBLE_PADDING[0], BUBBLE_PADDING[1])
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setStyleSheet(f"color: {color}; background: transparent; font-size: 13.5px;")
        inner.addWidget(self.body)

        meta = QLabel(f"{'Tú' if mine else ('Error' if role == 'error' else 'LOT Bot')} · {now:%H:%M}")
        meta.setObjectName("ChatMeta")

        if mine:
            row.addStretch(1)
            column.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight)
            column.addWidget(meta, 0, Qt.AlignmentFlag.AlignRight)
            row.addLayout(column)
        else:
            avatar = QLabel()
            avatar.setPixmap(_logo(28))
            avatar.setFixedSize(28, 28)
            avatar.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            column.addWidget(meta)
            column.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignLeft)
            row.addLayout(column)
            row.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def fit(self, chat_width: int) -> None:
        """Ancho de la burbuja: el del texto, como mucho una parte del chat."""
        if self.bubble is None or self.body is None:
            return
        limit = max(220, int(chat_width * BUBBLE_RATIO))
        metrics = self.body.fontMetrics()
        natural = max((metrics.horizontalAdvance(line) for line in self.text.splitlines() or [""]), default=0)
        width = min(limit, natural + 2 * BUBBLE_PADDING[0] + 6)
        self.bubble.setFixedWidth(max(width, 60))


class _EnterToSend(QObject):
    """Enter envía; Mayús+Enter hace una línea nueva."""

    def __init__(self, send) -> None:
        super().__init__()
        self._send = send

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - firma de Qt
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._send()
                return True
        return False


class AssistantView(BaseView):
    title = "Asistente IA"
    subtitle = "¿Qué quieres hacer?"

    def build(self) -> None:
        self.add_header_button("Nueva conversación", self._reset)

        # --- Aviso del proveedor de IA ---
        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        self.provider_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        self.body.addWidget(self.provider_label)

        # --- Conversación ---
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("Content")
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        self.chat_column = QWidget()
        self.chat_column.setMaximumWidth(CHAT_MAX_WIDTH)
        self.chat_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.chat_layout = QVBoxLayout(self.chat_column)
        self.chat_layout.setContentsMargins(4, 8, 12, 8)
        self.chat_layout.setSpacing(14)
        self.chat_layout.addStretch(1)
        outer.addWidget(self.chat_column, 100)
        outer.addStretch(1)
        self.scroll.setWidget(container)
        self.scroll.viewport().installEventFilter(self)
        # Bajar solo al final cuando llega un mensaje nuevo: se espera a que
        # la zona del chat crezca (el tamaño nuevo llega después de añadirlo).
        self._follow = True
        self.scroll.verticalScrollBar().rangeChanged.connect(self._on_range_changed)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_user_scroll)
        self.body.addWidget(self.scroll, 1)

        # --- Panel de confirmación ---
        self.confirmation = ConfirmationPanel()
        self.confirmation.confirmed.connect(self._on_confirmed)
        self.confirmation.cancelled.connect(self._on_cancelled)
        self.body.addWidget(self.confirmation)

        # --- Ejemplos ---
        self.examples_row = QHBoxLayout()
        self.examples_row.setSpacing(6)
        for example in EXAMPLES[:4]:
            button = QPushButton(example)
            button.setObjectName("ChatChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, text=example: self._use_example(text))
            self.examples_row.addWidget(button)
        self.examples_row.addStretch(1)

        # --- Entrada: una sola caja con el botón dentro ---
        input_box = QFrame()
        input_box.setObjectName("ChatInput")
        row = QHBoxLayout(input_box)
        row.setContentsMargins(14, 8, 8, 8)
        row.setSpacing(8)
        self.input = QTextEdit()
        self.input.setObjectName("ChatInputText")
        self.input.setPlaceholderText(
            "Escribe lo que quieres hacer. Por ejemplo: «Empieza a subir anuncios cada 60 "
            "segundos». Enter envía; Mayús+Enter, otra línea."
        )
        self.input.setFixedHeight(64)
        self._enter_filter = _EnterToSend(self._send)
        self.input.installEventFilter(self._enter_filter)
        row.addWidget(self.input, 1)
        self.send_button = QPushButton("Enviar")
        self.send_button.setObjectName("Primary")
        self.send_button.setMinimumHeight(38)
        self.send_button.clicked.connect(self._send)
        row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        # Sugerencias y caja de escribir, alineadas con la conversación.
        composer = QWidget()
        composer.setMaximumWidth(CHAT_MAX_WIDTH)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(4, 0, 12, 0)
        composer_layout.setSpacing(8)
        composer_layout.addLayout(self.examples_row)
        composer_layout.addWidget(input_box)
        centered = QHBoxLayout()
        centered.addStretch(1)
        centered.addWidget(composer, 100)
        centered.addStretch(1)
        self.body.addLayout(centered)

        self._greet()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        provider = self.app.agent.provider
        mode = "MODO DEMO — los cambios no afectan a Wallapop." if self.app.demo_mode else ""
        extra = (
            ""
            if provider.natural_language
            else " Escribe órdenes concretas; para lenguaje libre configura una clave de IA en Ajustes."
        )
        self.provider_label.setText(f"Asistente: {provider.describe()}.{extra} {mode}".strip())

    # ------------------------------------------------------------------
    def _greet(self) -> None:
        self._add_bubble(
            "asistente",
            "Hola. Dime qué quieres hacer con tus cuentas de Wallapop.\n"
            "Antes de publicar, modificar o eliminar cualquier cosa te pediré confirmación.",
        )

    def _use_example(self, text: str) -> None:
        self.input.setPlainText(text)
        self.input.setFocus()

    def _reset(self) -> None:
        self.app.agent.reset()
        self.confirmation.clear()
        self._typing = None
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._greet()

    # ------------------------------------------------------------------
    def _add_bubble(self, role: str, text: str, tool_name: str | None = None) -> ChatBubble:
        if role == "herramienta":
            tool_name = self._tool_label(tool_name)
        bubble = ChatBubble(role, text, tool_name)
        bubble.fit(self._chat_width())
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self._scroll_to_bottom()
        return bubble

    def _tool_label(self, name: str | None) -> str:
        """Lo que ha hecho LOT Bot, con palabras (no el nombre técnico)."""
        registry = getattr(self.app.agent, "_registry", None)
        tool = registry.get(name) if registry is not None and name else None
        if tool is None or not tool.description:
            return "Acción hecha"
        first = tool.description.split(". ")[0].rstrip(".")
        return first if len(first) <= 80 else first[:77] + "…"

    def _chat_width(self) -> int:
        return min(CHAT_MAX_WIDTH, self.scroll.viewport().width()) - 16

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - firma de Qt
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            width = self._chat_width()
            for index in range(self.chat_layout.count()):
                widget = self.chat_layout.itemAt(index).widget()
                if isinstance(widget, ChatBubble):
                    widget.fit(width)
        return super().eventFilter(obj, event)

    def _show_typing(self, show: bool) -> None:
        """«LOT Bot está escribiendo…» mientras se espera la respuesta."""
        current = getattr(self, "_typing", None)
        if current is not None:
            current.deleteLater()
            self._typing = None
        if show:
            self._typing = self._add_bubble("asistente", "Pensando…")
            self._typing.body.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-style: italic;")

    def _scroll_to_bottom(self) -> None:

        self._follow = True
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _on_user_scroll(self, value: int) -> None:
        # Si subes para leer algo, no se te baja de golpe hasta el próximo mensaje.
        self._follow = value >= self.scroll.verticalScrollBar().maximum() - 30

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        if getattr(self, "_follow", False):
            self.scroll.verticalScrollBar().setValue(maximum)

    # ------------------------------------------------------------------
    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self._add_bubble("usuario", text)
        self._set_busy(True)
        self.run_task(
            lambda: self.app.agent.ask(text),
            on_success=self._on_response,
            on_done=lambda: self._set_busy(False),
        )

    #: Si una respuesta tarda más que esto, se libera el botón y se avisa (la
    #: tarea sigue en segundo plano y su resultado aparecerá al terminar).
    WATCHDOG_MS = 90_000

    def _set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self._show_typing(busy)
        if not hasattr(self, "_watchdog"):
            from PySide6.QtCore import QTimer

            self._watchdog = QTimer(self)
            self._watchdog.setSingleShot(True)
            self._watchdog.timeout.connect(self._on_watchdog)
        if busy:
            self._watchdog.start(self.WATCHDOG_MS)
        else:
            self._watchdog.stop()

    def _on_watchdog(self) -> None:
        if self.send_button.isEnabled():
            return
        self._set_busy(False)
        self._add_bubble(
            "asistente",
            "Esto está tardando más de lo normal. Sigue en segundo plano y te mostraré el "
            "resultado cuando termine; mientras tanto puedes seguir escribiendo. Si ves que no "
            "llega, mira «Logs y errores».",
        )

    def _on_response(self, response: AgentResponse) -> None:
        for message in response.messages:
            if message.role == "sistema":
                continue  # lo muestra el panel de confirmación
            self._add_bubble(message.role, message.text, message.tool_name)

        if response.needs_confirmation and response.pending is not None:
            request = response.pending.request
            self.confirmation.show_request(
                request.token, request.title, request.lines, request.destructive
            )
        else:
            self.confirmation.clear()
        self._notify_refresh()

    # ------------------------------------------------------------------
    def _on_confirmed(self, token: str) -> None:
        self._add_bubble("usuario", "Confirmado.")
        self._set_busy(True)
        self.run_task(
            lambda: self.app.agent.confirm(token),
            on_success=self._on_response,
            on_done=lambda: self._set_busy(False),
        )

    def _on_cancelled(self, token: str) -> None:
        self._add_bubble("usuario", "Cancelado.")
        self.run_task(lambda: self.app.agent.cancel(token), on_success=self._on_response)

    def _notify_refresh(self) -> None:
        """Avisa al resto de pantallas de que los datos pueden haber cambiado."""
        from lot_bot.core.events import TOPIC_CATALOG_CHANGED, TOPIC_LISTINGS_CHANGED

        self.app.events.publish(TOPIC_LISTINGS_CHANGED, {})
        self.app.events.publish(TOPIC_CATALOG_CHANGED, {})
