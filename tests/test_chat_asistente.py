"""Chat del asistente: tus mensajes a la derecha, los de LOT Bot a la
izquierda, las acciones con palabras (no nombres técnicos) y Enter envía."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.ui


@pytest.fixture()
def vista(app_with_data):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from lot_bot.ui.views.assistant import AssistantView
    from lot_bot.ui.widgets.workers import TaskRunner

    qt = QApplication.instance() or QApplication([])
    view = AssistantView(app_with_data, TaskRunner(2))
    view.resize(1200, 800)
    view.show()
    qt.processEvents()
    yield view, qt


def _burbujas(view):
    from lot_bot.ui.views.assistant import ChatBubble

    items = (view.chat_layout.itemAt(i).widget() for i in range(view.chat_layout.count()))
    return [w for w in items if isinstance(w, ChatBubble)]


def test_enter_envia_y_la_respuesta_llega_ordenada(vista):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    view, qt = vista
    pensando = []

    def en_el_momento(fn, on_success=None, on_done=None, **_k):
        # Sin hilos (la base de datos de pruebas está en memoria).
        pensando.append(any(b.text == "Pensando…" for b in _burbujas(view)))
        result = fn()
        if on_success:
            on_success(result)
        if on_done:
            on_done()

    view.run_task = en_el_momento
    view.input.setPlainText("Estado de las cuentas")
    qt.sendEvent(view.input, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    qt.processEvents()
    assert pensando == [True]  # mientras espera, «Pensando…»
    roles = [b.role for b in _burbujas(view)]
    assert roles[:2] == ["asistente", "usuario"]  # saludo y tu mensaje
    assert "herramienta" in roles and roles[-1] == "asistente"
    assert view.input.toPlainText() == ""
    assert not any(b.text == "Pensando…" for b in _burbujas(view))  # ya no está


def test_mayus_enter_hace_otra_linea(vista):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    view, qt = vista
    antes = len(_burbujas(view))
    view.input.setPlainText("Hola")
    filtro = view._enter_filter
    evento = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert filtro.eventFilter(view.input, evento) is False  # no envía
    assert len(_burbujas(view)) == antes


def test_las_acciones_se_explican_con_palabras(vista):
    view, _qt = vista
    etiqueta = view._tool_label("get_account_status")
    assert "get_account_status" not in etiqueta and len(etiqueta) <= 80
    assert view._tool_label("no_existe") == "Acción hecha"


def test_las_burbujas_no_ocupan_todo_el_ancho(vista):
    view, qt = vista
    corto = view._add_bubble("usuario", "Hola")
    largo = view._add_bubble("asistente", "palabra " * 200)
    qt.processEvents()
    ancho = view._chat_width()
    assert corto.bubble.width() < 150
    assert largo.bubble.width() <= int(ancho * 0.78) + 1
