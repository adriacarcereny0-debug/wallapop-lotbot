"""Errores reales encontrados en la revisión del código, con su prueba.

Cada prueba falla con el código anterior y pasa con la corrección.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from lot_bot.database.models import (
    PublishJob,
    PublishJobStatus,
    PublishTask,
    PublishTaskStatus,
    Setting,
)
from tests.test_browser_integration import SITE, FakePage, draft, make_service


@pytest.fixture()
def profiles(tmp_path):
    from lot_bot.wallapop.browser import BrowserProfileStore

    return BrowserProfileStore(tmp_path / "browser_profiles")


# ---------------------------------------------------------------------------
# 1. Precios: «1.250 €» son 1250 €, no 1,25 €
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texto", "precio"),
    [
        ("Sofá cama\n1.250 €", 1250.0),
        ("1.250,50 €", 1250.5),
        ("11,44 €", 11.44),
        ("11.44 €", 11.44),
        ("12 500 €", 12500.0),
        ("250\xa0€", 250.0),
        ("Pack 3\n120 €", 120.0),  # un salto de línea no une dos números
    ],
)
def test_el_precio_de_la_ficha_se_lee_bien(texto, precio):
    from lot_bot.wallapop.browser.service import _card_price, _shows_price

    assert _card_price(texto) == pytest.approx(precio)
    assert _shows_price(f"Precio {texto}", precio)


def test_el_campo_de_precio_con_miles_coincide_con_la_plantilla():
    from lot_bot.wallapop.browser.form import parse_price

    assert parse_price("1.250") == 1250.0
    assert parse_price("1.250,00") == 1250.0
    assert parse_price("11,44") == pytest.approx(11.44)


def test_el_titulo_de_la_ficha_no_es_el_precio():
    from lot_bot.wallapop.browser.service import _card_title

    assert _card_title("Sofá cama de matrimonio\n1.250 €") == "Sofá cama de matrimonio"


# ---------------------------------------------------------------------------
# 2. Eliminar: una página que aún carga NO es un anuncio eliminado
# ---------------------------------------------------------------------------
class PaginaLenta(FakePage):
    """El anuncio sigue en Wallapop, pero sus botones tardan en aparecer."""

    def first_visible(self, targets, timeout_ms=0):
        if self.url.startswith("https://es.wallapop.com/item/") and timeout_ms > 0:
            for target in targets:
                if target in SITE.delete.button:
                    return target
        return None


def test_eliminar_no_da_por_borrado_un_anuncio_que_sigue(profiles, tmp_path, monkeypatch):
    from lot_bot.wallapop.errors import BrowserStepError

    service, launcher = make_service(profiles, {"logged_in": True}, tmp_path)
    monkeypatch.setattr(SITE.delete, "wait_ms", 50)
    monkeypatch.setattr(SITE, "timeout_ms", 20000)  # otras pruebas lo dejan a 0
    import tests.test_browser_integration as base

    monkeypatch.setattr(base, "FakePage", PaginaLenta)
    with pytest.raises(BrowserStepError, match="sigue apareciendo"):
        service.delete_item("acc-1", "x", "https://es.wallapop.com/item/sofa-123")
    service.shutdown()


# ---------------------------------------------------------------------------
# 3. Publicar: un fallo DESPUÉS de pulsar «Publicar» queda «sin confirmar»
# ---------------------------------------------------------------------------
def test_un_fallo_tras_pulsar_publicar_no_se_da_por_fallido(profiles, tmp_path, monkeypatch):
    from lot_bot.wallapop.browser.form import ListingForm

    def se_rompe(self):
        raise RuntimeError("la página se ha quedado colgada")

    monkeypatch.setattr(ListingForm, "wait_for_publish_confirmation", se_rompe)
    world = {"logged_in": True, "item_url": "https://es.wallapop.com/item/canape-1"}
    service, _ = make_service(profiles, world, tmp_path)
    result = service.create_item("acc-1", draft(tmp_path))
    service.shutdown()
    assert world["submits"] == 1
    assert not result.success
    assert result.data["codigo"] == service.UNCONFIRMED_CODE  # se buscará; no se reintenta


def test_un_fallo_antes_de_pulsar_publicar_sigue_siendo_un_fallo(profiles, tmp_path):
    from lot_bot.wallapop.errors import BrowserStepError

    world = {"logged_in": True, "missing": {"precio"}}
    service, _ = make_service(profiles, world, tmp_path)
    SITE_TIMEOUT = SITE.timeout_ms
    SITE.timeout_ms = 50
    try:
        with pytest.raises(BrowserStepError):
            service.create_item("acc-1", draft(tmp_path))
    finally:
        SITE.timeout_ms = SITE_TIMEOUT
        service.shutdown()
    assert not world.get("submits")


OPCIONES = {"visible": False, "channels": [], "locale": "es-ES"}


# ---------------------------------------------------------------------------
# 4. Navegador por cuenta: un trabajo que llega al cerrarse por inactividad
# ---------------------------------------------------------------------------
def test_un_trabajo_que_llega_al_cerrarse_el_navegador_se_atiende(tmp_path):
    from lot_bot.wallapop.browser.pool import BrowserSessionPool
    from tests.test_browser_integration import FakeLauncher

    pool = BrowserSessionPool(FakeLauncher({}), idle_seconds=0.02)
    for _ in range(40):
        start = time.monotonic()
        assert pool.run("acc-1", tmp_path / "acc-1", lambda page: 1, timeout=5.0, **OPCIONES) == 1
        assert time.monotonic() - start < 3.0  # antes podía quedarse esperando
        time.sleep(0.02)
    pool.close_all()


def test_el_navegador_no_se_retira_si_tiene_trabajo_pendiente(tmp_path):
    from lot_bot.wallapop.browser.pool import BrowserSessionPool
    from tests.test_browser_integration import FakeLauncher

    pool = BrowserSessionPool(FakeLauncher({}), idle_seconds=60)
    pool.run("acc-1", tmp_path / "acc-1", lambda page: None, **OPCIONES)
    worker = pool._workers["acc-1"]
    bloqueo = threading.Event()
    worker.submit(lambda page: bloqueo.wait(2))
    worker.submit(lambda page: None)
    assert pool._retire(worker) is False  # hay trabajo: sigue abierto
    bloqueo.set()
    pool.close_all()


# ---------------------------------------------------------------------------
# 5. LOT Bot se cierra a mitad de publicar: no se vuelve a publicar solo
# ---------------------------------------------------------------------------
def _cola_con_tarea(app, estado):
    refs = [a.internal_ref for a in app.accounts.list_accounts()]
    job_id = app.publish_queue.enqueue_master(None, refs[:1], copies=2, start=False)
    with app.db.session_scope() as session:
        job = session.get(PublishJob, job_id)
        job.status = PublishJobStatus.RUNNING
        tareas = list(job.tasks)
        tareas[0].status = estado
        tareas[1].status = PublishTaskStatus.WAITING
        return job_id, tareas[0].id, tareas[1].id


def test_lo_que_se_estaba_publicando_al_cerrar_queda_sin_confirmar(app):
    job_id, publicando, esperando = _cola_con_tarea(app, PublishTaskStatus.PUBLISHING)
    app.publish_queue.recover_interrupted()
    with app.db.session_scope() as session:
        assert session.get(PublishTask, publicando).status is PublishTaskStatus.UNCONFIRMED
        assert "se cerró" in session.get(PublishTask, publicando).error
        assert session.get(PublishTask, esperando).status is PublishTaskStatus.PENDING
        assert session.get(PublishJob, job_id).status is PublishJobStatus.PAUSED


def test_un_anuncio_sin_confirmar_solo_se_reintenta_si_lo_pides(app):
    _job, tarea, _ = _cola_con_tarea(app, PublishTaskStatus.UNCONFIRMED)
    with pytest.raises(ValueError):
        app.publish_queue.retry_task(tarea)
    app.publish_queue.retry_task(tarea, allow_unconfirmed=True)
    with app.db.session_scope() as session:
        assert session.get(PublishTask, tarea).status is PublishTaskStatus.PENDING


# ---------------------------------------------------------------------------
# 6. No repetir fotos: una foto borrada del ordenador no bloquea la cola
# ---------------------------------------------------------------------------
def test_una_foto_borrada_del_ordenador_se_salta(app, tmp_path):
    from PIL import Image

    rutas = []
    for nombre in ("borrada.jpg", "buena.jpg"):
        ruta = tmp_path / nombre
        Image.new("RGB", (900, 700), (120, 110, 100) if nombre == "buena.jpg" else (10, 20, 30)).save(ruta)
        rutas.append(ruta)
    app.master_ads.add_images(
        None, [{"path": str(r), "file_format": "JPEG", "width": 900, "height": 700} for r in rutas]
    )
    rutas[0].unlink()
    libres = app.publish_queue.unused_photos(None)
    assert [Path(f["path"]).name for f in libres] == ["buena.jpg"]


# ---------------------------------------------------------------------------
# 7. Reintentos automáticos: un valor raro guardado no rompe la cola
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("guardado", "queda"), [("abc", 0), (None, 0), (7, 3), (-2, 0), ("1", 1)])
def test_reintentos_automaticos_con_valores_raros(app, guardado, queda):
    with app.db.session_scope() as session:
        session.merge(Setting(key="publicacion", value={"automatic_retries": guardado}))
    assert app.publish_queue.settings()["automatic_retries"] == queda


# ---------------------------------------------------------------------------
# 8. Clave maestra: si el llavero no responde, NO se crea otra
# ---------------------------------------------------------------------------
def test_si_el_llavero_falla_no_se_sustituye_la_clave(temp_paths, monkeypatch):
    from lot_bot.config import secrets

    escrito = []

    class LlaveroBloqueado:
        def get_password(self, *_a):
            raise RuntimeError("llavero bloqueado")

        def set_password(self, *a):
            escrito.append(a)

    monkeypatch.delenv("LOT_BOT_MASTER_KEY", raising=False)
    monkeypatch.setattr(secrets, "_keyring", lambda: LlaveroBloqueado())
    clave = secrets.get_master_key()
    assert clave  # se puede seguir usando LOT Bot en esta sesión
    assert escrito == []  # la clave buena del llavero no se pisa
    assert not secrets._key_file().exists()  # ni se crea otra en un fichero


def test_sin_llavero_se_usa_el_fichero_como_siempre(temp_paths, monkeypatch):
    from lot_bot.config import secrets

    class SinLlavero:
        def get_password(self, *_a):
            raise type("NoKeyringError", (Exception,), {})("no hay")

        def set_password(self, *_a):
            raise type("NoKeyringError", (Exception,), {})("no hay")

    monkeypatch.delenv("LOT_BOT_MASTER_KEY", raising=False)
    monkeypatch.setattr(secrets, "_keyring", lambda: SinLlavero())
    primera = secrets.get_master_key()
    assert secrets._key_file().exists()
    assert secrets.get_master_key() == primera  # la misma en el siguiente arranque


# ---------------------------------------------------------------------------
# 9. Registro sin consola (pythonw en Windows, .exe, .app)
# ---------------------------------------------------------------------------
def test_sin_consola_el_registro_no_da_errores(temp_paths, monkeypatch):
    import logging

    from lot_bot.logs import setup

    monkeypatch.setattr(setup, "_configured", False)
    monkeypatch.setattr("sys.stderr", None)
    root = logging.getLogger()
    antes = list(root.handlers)
    try:
        setup.configure_logging("INFO")
        assert all(type(h) is not logging.StreamHandler for h in root.handlers)
        logging.getLogger("prueba").info("hola sin consola")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = antes
        monkeypatch.setattr(setup, "_configured", False)
