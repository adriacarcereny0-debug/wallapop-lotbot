"""Abre LOT Bot en MODO DEMO (sin pantalla) y recorre TODO lo que se puede
pulsar: pantallas, pestañas, botones, desplegables y casillas.

Para cada cosa guarda qué pasa al pulsarla:
  - otra pantalla o pestaña  -> "ir"   (otra captura)
  - una ventana o un aviso   -> "ventana" (captura de esa ventana)
  - cambia la pantalla       -> "ir"   (captura de cómo queda)
  - un desplegable           -> "lista" (sus opciones)
  - lo demás                 -> "nota" (qué hace, en una frase)

Uso: python capturar_clic.py <carpeta de salida>
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
shutil.rmtree(out, ignore_errors=True)
(out / "img").mkdir(parents=True)
data_dir = Path("/home/demo/LOT Bot")
shutil.rmtree(data_dir, ignore_errors=True)
data_dir.mkdir(parents=True)
os.environ["LOT_BOT_DATA_DIR"] = str(data_dir)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LOT_BOT_UPDATE_CHECK"] = "0"  # la demo no busca actualizaciones

from PySide6.QtCore import QBuffer, QIODevice, QLocale  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QToolButton,
)

from lot_bot.bootstrap import create_application, seed_demo_catalog  # noqa: E402
from lot_bot.config.settings import Settings  # noqa: E402
from lot_bot.publishing.queue import FakeClock  # noqa: E402
from lot_bot.ui.main_window import NAVIGATION, MainWindow  # noqa: E402
from lot_bot.ui.theme import stylesheet  # noqa: E402

QLocale.setDefault(QLocale(QLocale.Language.Spanish, QLocale.Country.Spain))
qt = QApplication([])
qt.setStyle("Fusion")
qt.setStyleSheet(stylesheet())

app = create_application(
    settings=Settings(LOT_BOT_DEMO_MODE=True, LOT_BOT_AI_PROVIDER="rules", LOT_BOT_LOG_LEVEL="INFO"),
    start_scheduler=False,
)
for log in (data_dir / "logs").glob("*.log"):
    log.write_text("", encoding="utf-8")
seed_demo_catalog(app)
refs = [a.internal_ref for a in app.accounts.list_accounts()]
app.listings.sync_all(refs)
app.messages.sync_all(refs)
cola = app.publish_queue
cola.clock = FakeClock()
cola.enqueue_master(None, refs[:2], copies=8)
for _ in range(5):
    cola.run_once()

# Fotos de ejemplo en «Imágenes» (para que no salga vacía).
from PIL import Image, ImageDraw  # noqa: E402

for i, (color, nombre) in enumerate(
    [((120, 110, 100), "canape-gris.jpg"), ((150, 135, 115), "canape-roble.jpg"), ((95, 100, 110), "dormitorio.jpg")]
):
    ruta = data_dir / nombre
    im = Image.new("RGB", (1200, 900), color)
    d = ImageDraw.Draw(im)
    d.rectangle((200 + i * 20, 380, 1000 - i * 20, 640), fill=tuple(min(255, c + 60) for c in color))
    d.rectangle((200 + i * 20, 300, 1000 - i * 20, 380), fill=tuple(min(255, c + 90) for c in color))
    im.save(ruta, quality=90)
    try:
        app.image_generation.add_own_image(ruta)
    except Exception as exc:  # una foto de ejemplo no debe parar la captura
        print("foto:", exc)

win = MainWindow(app)
W, H = 1600, 900
win.resize(W, H)
win.show()


def settle(n=25):
    for _ in range(n):
        qt.processEvents()
    win.runner.wait(3000)
    win.assistant_runner.wait(3000)
    for _ in range(n):
        qt.processEvents()


settle()

# Una pregunta al asistente, para que no salga vacío.
vista = win.views[0]
caja = getattr(vista, "input", None) or getattr(vista, "entry", None)
if caja is not None and hasattr(vista, "_send"):
    caja.setText("Estado de las cuentas")
    vista._send()
    settle(60)

# --------------------------------------------------------------------------
# Ventanas: en vez de esperar a que alguien las cierre, se fotografían y se
# cierran (como si se pulsara «Cancelar»). Nunca se confirma nada.
# --------------------------------------------------------------------------
abiertas: list[dict] = []


def _foto_ventana(dialog) -> str:
    dialog.adjustSize()
    dialog.show()
    for _ in range(20):
        qt.processEvents()
    return guardar(dialog.grab(), "v")


def _exec_falso(self, *a, **k):
    try:
        abiertas.append({"tipo": "ventana", "img": _foto_ventana(self), "titulo": self.windowTitle()})
    finally:
        self.close()
    return 0


QDialog.exec = _exec_falso
QMessageBox.exec = _exec_falso


def _archivo(texto):
    def falso(*a, **k):
        abiertas.append({"tipo": "nota", "texto": texto})
        return ([], "") if "Names" in texto else ("", "")
    return falso


QFileDialog.getOpenFileNames = staticmethod(_archivo("Se abre la ventana de tu ordenador para elegir fotos (puedes elegir varias)."))
QFileDialog.getOpenFileName = staticmethod(_archivo("Se abre la ventana de tu ordenador para elegir un archivo."))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: abiertas.append({"tipo": "nota", "texto": "Se abre la ventana de tu ordenador para elegir una carpeta."}) or "")
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: abiertas.append({"tipo": "nota", "texto": "Te pide que cuentes en pocas palabras qué ha pasado y crea en el Escritorio un .zip para enviar a soporte (sin contraseñas, cookies ni claves)."}) or ("", False))
QInputDialog.getText = staticmethod(lambda *a, **k: abiertas.append({"tipo": "nota", "texto": f"Te pregunta: «{a[2] if len(a) > 2 else ''}» y escribes la respuesta."}) or ("", False))


# --------------------------------------------------------------------------
_hashes: dict[str, str] = {}
_n = [0]


def guardar(pixmap, prefijo) -> str:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    data = bytes(buf.data())
    h = hashlib.sha1(data).hexdigest()
    if h in _hashes:
        return _hashes[h]
    _n[0] += 1
    nombre = f"{prefijo}{_n[0]:03d}.png"
    (out / "img" / nombre).write_bytes(data)
    _hashes[h] = nombre
    return nombre


def caja(w):
    """Dónde está el elemento dentro de la ventana (fracciones 0..1), solo la
    parte que se ve."""
    region = w.visibleRegion().boundingRect()
    if region.isEmpty() or not w.isVisible():
        return None
    p = w.mapTo(win, region.topLeft())
    x, y, ww, hh = p.x(), p.y(), region.width(), region.height()
    if ww < 6 or hh < 6 or x >= W or y >= H:
        return None
    return {"x": x / W, "y": y / H, "w": min(ww, W - x) / W, "h": min(hh, H - y) / H}


def texto_de(w) -> str:
    t = ""
    if isinstance(w, QAbstractButton):
        t = w.text().strip() or w.toolTip()
    return " ".join(t.split())


estados: dict[str, dict] = {}
NAV = []


def foto_estado(sid, titulo, i, tab_widget=None, tab=None):
    img = guardar(win.grab(), "p")
    estados[sid] = {"img": img, "titulo": titulo, "vista": i, "zonas": []}
    return estados[sid]


def zonas_nav(estado):
    for k, b in enumerate(win.nav_buttons):
        c = caja(b)
        if c:
            estado["zonas"].append({**c, "tipo": "ir", "a": f"s{k}", "etiqueta": NAVIGATION[k][0], "nav": True})


def volver_a(i, tab_widget_idx=None, tab=None):
    win._go_to(i)
    settle()
    if tab_widget_idx is not None:
        tabs = tabs_de(win.views[i])
        if tab_widget_idx < len(tabs):
            tabs[tab_widget_idx].setCurrentIndex(tab)
            settle()


def tabs_de(view):
    return [t for t in view.findChildren(QTabWidget) if t.isVisible()]


def pulsables(view):
    """Botones, desplegables, casillas y campos de texto que se ven."""
    vistos = []
    for w in view.findChildren(QAbstractButton) + view.findChildren(QComboBox) + view.findChildren(QLineEdit) + view.findChildren(QTextEdit) + view.findChildren(QPlainTextEdit):
        if w in win.nav_buttons or not w.isVisible() or caja(w) is None:
            continue
        if isinstance(w, QLineEdit) and isinstance(w.parent(), QComboBox):
            continue
        if w.objectName().startswith("qt_") or type(w).__name__ in ("QTabBar",):
            continue
        vistos.append(w)
    return vistos


def explorar(sid, i, titulo, tab_ctx=None):
    """Captura el estado y prueba cada cosa pulsable de la pantalla."""
    estado = foto_estado(sid, titulo, i)
    zonas_nav(estado)
    view = win.views[i]
    # Pestañas (solo las de primer nivel de la pantalla).
    for ti, tw in enumerate(tabs_de(view)):
        bar = tw.tabBar()
        for j in range(tw.count()):
            r = bar.tabRect(j)
            p = bar.mapTo(win, r.topLeft())
            if r.isEmpty():
                continue
            destino = f"s{i}" if j == 0 else f"s{i}t{ti}_{j}"
            estado["zonas"].append({"x": p.x() / W, "y": p.y() / H, "w": r.width() / W, "h": r.height() / H,
                                    "tipo": "ir", "a": destino, "etiqueta": f"Pestaña «{tw.tabText(j)}»"})
    base_img = estado["img"]
    for w in pulsables(view):
        c = caja(w)
        if c is None:
            continue
        nombre = texto_de(w)
        if isinstance(w, QComboBox):
            opciones = [w.itemText(k) for k in range(w.count()) if w.itemText(k)]
            estado["zonas"].append({**c, "tipo": "lista", "opciones": opciones[:40], "etiqueta": "Desplegable"})
            continue
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            ph = w.placeholderText() if hasattr(w, "placeholderText") else ""
            estado["zonas"].append({**c, "tipo": "nota", "texto": "Aquí escribes" + (f": «{ph}»" if ph else ".")})
            continue
        if isinstance(w, QCheckBox):
            estado["zonas"].append({**c, "tipo": "nota", "texto": f"Casilla para activar o desactivar: «{nombre}»."})
            continue
        if not w.isEnabled():
            estado["zonas"].append({**c, "tipo": "nota", "texto": f"«{nombre}» está desactivado ahora (no tiene sentido en este momento)."})
            continue
        if isinstance(w, (QPushButton, QToolButton)):
            abiertas.clear()
            antes = win.grab().toImage()
            try:
                w.click()
            except Exception as exc:  # un botón que falla no para la captura
                print("botón", nombre, exc)
            settle()
            cambio = win.grab().toImage() != antes
            zona = {**c, "etiqueta": nombre}
            ventanas = [a for a in abiertas if a["tipo"] == "ventana"]
            notas = [a["texto"] for a in abiertas if a["tipo"] == "nota"]
            if ventanas:
                zona.update(tipo="ventana", imgs=[v["img"] for v in ventanas][:3])
            elif notas:
                zona.update(tipo="nota", texto=notas[0])
            elif cambio:
                nuevo = guardar(win.grab(), "p")
                if nuevo != base_img:
                    sub = f"{sid}b{len(estado['zonas'])}"
                    estados[sub] = {"img": nuevo, "titulo": f"{titulo} · tras pulsar «{nombre}»", "vista": i, "zonas": []}
                    zonas_nav(estados[sub])
                    zona.update(tipo="ir", a=sub)
                else:
                    zona.update(tipo="nota", texto=f"«{nombre}»: en el programa hace esta acción.")
            else:
                zona.update(tipo="nota", texto=f"«{nombre}»: en el programa hace esta acción al momento.")
            estado["zonas"].append(zona)
            # Se vuelve a dejar la pantalla como estaba.
            volver_a(i, *(tab_ctx or (None, None)))


from PySide6.QtWidgets import QTableWidget  # noqa: E402


def elegir_primera_fila(view):
    """Con una fila elegida se activan los botones que dependen de ella."""
    for t in view.findChildren(QTableWidget):
        if t.isVisible() and t.rowCount():
            t.selectRow(0)
            settle(10)
            return


_volver_original = volver_a


def volver_a(i, tab_widget_idx=None, tab=None):  # noqa: F811
    _volver_original(i, tab_widget_idx, tab)
    if NAVIGATION[i][1] in ("cuentas", "productos", "anuncios"):
        elegir_primera_fila(win.views[i])


for i, (label, icon, _cls) in enumerate(NAVIGATION):
    volver_a(i)
    if icon == "imagenes":
        lista = getattr(win.views[i], "images", None)
        if lista is not None and lista.count():
            lista.setCurrentRow(0)
            settle()
    explorar(f"s{i}", i, label)
    for ti, tw in enumerate(tabs_de(win.views[i])):
        for j in range(1, tw.count()):
            volver_a(i, ti, j)
            explorar(f"s{i}t{ti}_{j}", i, f"{label} · {tw.tabText(j)}", (ti, j))
    print("pantalla", label, "->", sum(1 for s in estados.values() if s["vista"] == i), "estados")

(out / "demo.json").write_text(json.dumps(
    {"ancho": W, "alto": H, "pantallas": [n for n, _i, _c in NAVIGATION], "iconos": [ic for _n, ic, _c in NAVIGATION], "estados": estados},
    ensure_ascii=False, indent=1), encoding="utf-8")
print("hecho", len(estados), "estados,", len(list((out / "img").glob("*.png"))), "imágenes")
app.shutdown()
