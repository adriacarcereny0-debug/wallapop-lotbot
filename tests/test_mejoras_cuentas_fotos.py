"""Mejoras: fotos que faltan, anuncios sin confirmar, elegir varias cuentas y
publicar en varias cuentas A LA VEZ (una cola y un navegador por cuenta)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from lot_bot.database.models import PublishJob, PublishTask, PublishTaskStatus
from lot_bot.publishing.queue import UNCONFIRMED_CODE, FakeClock
from lot_bot.wallapop.dto import OperationResult


def _refs(app):
    return [a.internal_ref for a in app.accounts.list_accounts() if a.is_connected]


def _fotos(app, tmp_path, n, prefijo="foto"):
    from PIL import Image

    rutas = []
    for i in range(n):
        ruta = tmp_path / f"{prefijo}-{i}.jpg"
        Image.new("RGB", (900, 700), (40 * i % 255, 110, 100)).save(ruta)
        rutas.append(ruta)
    app.master_ads.add_images(
        None, [{"path": str(r), "file_format": "JPEG", "width": 900, "height": 700} for r in rutas]
    )
    return rutas


@pytest.fixture()
def app_fichero(temp_paths, demo_settings, tmp_path):
    """Como `app`, pero con la base de datos en un fichero: varios hilos la
    comparten (la de memoria es una distinta por hilo)."""
    from lot_bot.bootstrap import create_application
    from lot_bot.database.engine import Database, set_database

    db = Database(f"sqlite:///{tmp_path / 'lotbot.db'}")
    db.create_all()
    set_database(db)
    app = create_application(settings=demo_settings, database=db, start_scheduler=False)
    app.publish_queue.clock = FakeClock()
    yield app
    app.publish_queue.shutdown()
    app.automations.shutdown()
    set_database(None)
    db.dispose()


# ===========================================================================
# 3. Elegir exactamente las cuentas que quieras (2 de 4, 3 de 5...)
# ===========================================================================
@pytest.mark.parametrize(
    ("respuesta", "esperadas"),
    [
        ("1 y 3", ["Cuenta 1 (DEMO)", "Cuenta 3 (DEMO)"]),
        ("las cuentas 2, 3 y 4", ["Cuenta 2 (DEMO)", "Cuenta 3 (DEMO)", "Cuenta 4 (DEMO)"]),
        ("Cuenta 4 (DEMO) y Cuenta 2 (DEMO)", ["Cuenta 2 (DEMO)", "Cuenta 4 (DEMO)"]),
        ("todas", ["Cuenta 1 (DEMO)", "Cuenta 2 (DEMO)", "Cuenta 3 (DEMO)", "Cuenta 4 (DEMO)"]),
        ("la 2", ["Cuenta 2 (DEMO)"]),
    ],
)
def test_se_entienden_las_cuentas_elegidas(app, respuesta, esperadas):
    from lot_bot.ai.tools.master_ad_tools import _pick_accounts

    cuentas = [a for a in app.accounts.list_accounts() if a.is_connected]
    alias = {a.internal_ref: a.alias for a in cuentas}
    assert [alias[r] for r in _pick_accounts(respuesta, cuentas)] == esperadas


def test_el_asistente_publica_solo_en_las_cuentas_elegidas(app):
    agente = app.agent
    agente.ask("Empieza a subir anuncios")
    r = agente.ask("1 y 3")
    assert "¿Cuántos anuncios" in " ".join(m.text for m in r.messages)
    r = agente.ask("4")
    assert r.needs_confirmation
    lineas = r.pending.request.lines
    assert any("Cuenta 1 (DEMO): 2" in linea for linea in lineas)
    assert any("Cuenta 3 (DEMO): 2" in linea for linea in lineas)
    assert not any("Cuenta 2 (DEMO)" in linea or "Cuenta 4 (DEMO)" in linea for linea in lineas)
    agente.confirm(r.pending.request.token)
    app.publish_queue.run_until_idle()
    progreso = app.publish_queue.progress()
    assert progreso.published == 4
    assert {t["cuenta"] for t in progreso.tasks} == {"Cuenta 1 (DEMO)", "Cuenta 3 (DEMO)"}


def test_varias_cuentas_en_la_misma_frase(app):
    r = app.agent.ask("Empieza a subir 6 anuncios en las cuentas 2 y 4")
    assert r.needs_confirmation, [m.text for m in r.messages]
    lineas = r.pending.request.lines
    assert any("Cuenta 2 (DEMO): 3" in linea for linea in lineas)
    assert any("Cuenta 4 (DEMO): 3" in linea for linea in lineas)


@pytest.mark.ui
def test_el_dialogo_deja_marcar_las_cuentas_que_quieras(app):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from lot_bot.ui.views.master_ad import PublishDialog

    QApplication.instance() or QApplication([])
    dialogo = PublishDialog(app)
    assert dialogo.count_label.text() == "4 de 4 cuentas marcadas"
    dialogo._mark(False)
    dialogo.checks[1][1].setChecked(True)
    dialogo.checks[3][1].setChecked(True)
    assert dialogo.count_label.text() == "2 de 4 cuentas marcadas"
    refs, _copias, _cambios = dialogo.selection()
    assert refs == [dialogo.checks[1][0], dialogo.checks[3][0]]
    dialogo.parallel.setChecked(True)
    assert dialogo.parallel_selected()
    dialogo._mark(False)
    dialogo.checks[0][1].setChecked(True)
    assert not dialogo.parallel_selected()  # con una sola cuenta no hay «a la vez»


# ===========================================================================
# 4. Varias cuentas A LA VEZ
# ===========================================================================
def test_cuatro_cuentas_publican_a_la_vez_cada_una_su_anuncio(app_fichero, tmp_path):
    app = app_fichero
    _fotos(app, tmp_path, 4)
    refs = _refs(app)
    assert len(refs) == 4
    queue = app.publish_queue
    barrera = threading.Barrier(4, timeout=20)  # solo se abre si están las 4 A LA VEZ
    original = app.master_ads.publish_single
    llamadas = []

    def publicar(key, ref, overrides, **kw):
        llamadas.append(
            {"cuenta": ref, "hilo": threading.current_thread().name, "foto": kw["only_images"][0]}
        )
        barrera.wait()
        return original(key, ref, overrides, **kw)

    app.master_ads.publish_single = publicar
    job = queue.enqueue_master(None, refs, copies=4, generate_images=False, parallel=True)
    queue.run_parallel_until_idle()

    progreso = queue.progress(job)
    assert progreso.status == "completed", progreso.pause_reason
    assert progreso.parallel and progreso.published == 4
    # Cada cuenta en su propio hilo (su cola) y nunca uno de otra cuenta.
    assert sorted(c["cuenta"] for c in llamadas) == sorted(refs)
    assert all(c["hilo"] == f"lotbot-cola-{c['cuenta']}" for c in llamadas)
    # Cada anuncio con una foto distinta (dos cuentas nunca cogen la misma).
    assert len({c["foto"] for c in llamadas}) == 4
    # Cada anuncio publicado en SU cuenta (no se mezclan los resultados).
    for tarea in progreso.tasks:
        remotos = {i.item_id for i in app.wallapop.list_items(tarea["cuenta_ref"], limit=500)}
        assert tarea["id_wallapop"] in remotos


def test_a_la_vez_cada_cuenta_sigue_su_cola_en_orden(app_fichero, tmp_path):
    app = app_fichero
    _fotos(app, tmp_path, 8)
    refs = _refs(app)
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs, copies=8, generate_images=False, parallel=True)
    queue.run_parallel_until_idle()
    progreso = queue.progress(job)
    assert progreso.status == "completed" and progreso.published == 8
    with app.db.session_scope() as session:
        tareas = session.query(PublishTask).filter(PublishTask.job_id == job).all()
        for ref in refs:
            propias = sorted((t for t in tareas if t.account_ref == ref), key=lambda t: t.position)
            assert len(propias) == 2
            # El segundo anuncio de la cuenta respeta el ritmo de ESA cuenta.
            espera = (propias[1].started_at - propias[0].started_at).total_seconds()
            assert espera >= queue.settings()["account_interval_seconds"]


def test_si_una_cuenta_pide_verificacion_las_demas_siguen(app_fichero, tmp_path):
    app = app_fichero
    _fotos(app, tmp_path, 4)
    refs = _refs(app)
    queue = app.publish_queue
    resuelta = threading.Event()
    publicados = []
    visto = {}
    original = app.master_ads.publish_single

    def publicar(key, ref, overrides, **kw):
        if ref == refs[0]:
            # Wallapop pide una verificación en la cuenta 1: la persona tarda.
            assert queue._user_gate(ref, "verificación", solved=resuelta.is_set, can_defer=True)
        resultado = original(key, ref, overrides, **kw)
        publicados.append(ref)
        return resultado

    def persona():
        """Completa la verificación cuando las otras 3 ya han publicado."""
        import time

        limite = time.monotonic() + 20
        while time.monotonic() < limite:
            if len(publicados) == 3 and refs[0] in queue.verifying_accounts():
                visto["estado"] = queue.progress(job).status
                visto["otras"] = sorted(publicados)
                break
            time.sleep(0.05)
        resuelta.set()

    app.master_ads.publish_single = publicar
    job = queue.enqueue_master(None, refs, copies=4, generate_images=False, parallel=True)
    vigilante = threading.Thread(target=persona, daemon=True)
    vigilante.start()
    queue.run_parallel_until_idle()
    vigilante.join(5)
    # Mientras la cuenta 1 esperaba, las otras 3 publicaron y la cola NO se pausó.
    assert visto == {"estado": "running", "otras": sorted(refs[1:])}
    progreso = queue.progress(job)
    assert progreso.status == "completed" and progreso.published == 4
    assert publicados[-1] == refs[0]  # la de la verificación, al completarla
    assert not queue.verifying_accounts()


def test_por_turnos_sigue_siendo_lo_de_siempre(app):
    queue = app.publish_queue
    assert queue.settings()["parallel_accounts"] is False
    job = queue.enqueue_master(None, _refs(app)[:2], copies=2, generate_images=False)
    assert queue.progress(job).parallel is False
    queue.run_until_idle()
    assert queue.progress(job).published == 2


def test_una_base_de_datos_antigua_recibe_la_columna_nueva(tmp_path):
    from sqlalchemy import inspect, text

    from lot_bot.database.engine import Database

    db = Database(f"sqlite:///{tmp_path / 'antigua.db'}")
    db.create_all()
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE publish_jobs DROP COLUMN parallel"))
    assert "parallel" not in {c["name"] for c in inspect(db.engine).get_columns("publish_jobs")}
    db.create_all()  # al arrancar LOT Bot
    assert "parallel" in {c["name"] for c in inspect(db.engine).get_columns("publish_jobs")}
    db.dispose()


# ===========================================================================
# 1. Fotos que faltan o están dañadas
# ===========================================================================
def test_si_falta_una_foto_no_se_publica_con_menos_sin_avisar(app, tmp_path):
    rutas = _fotos(app, tmp_path, 3)
    rutas[1].unlink()
    queue = app.publish_queue
    queue.save_settings(rotate_photos=False)
    assert [m["nombre"] for m in queue.missing_photos(None)] == ["foto-1.jpg"]

    job = queue.enqueue_master(None, _refs(app)[:1], copies=2, generate_images=False)
    queue.run_until_idle()
    progreso = queue.progress(job)
    assert progreso.published == 0
    assert progreso.status == "paused"
    assert "Faltan 1 foto" in progreso.pause_reason and "foto-1.jpg" in progreso.pause_reason
    assert all(t["estado"] == "pending" for t in progreso.tasks)  # nada se pierde

    queue.resume(job)  # «Continuar»: con las 2 que quedan
    queue.run_until_idle()
    assert queue.progress(job).published == 2
    assert any("Publicar con las fotos que quedan" in e.action for e in app.audit.recent(limit=30))


def test_una_foto_danada_se_detecta(app, tmp_path):
    rutas = _fotos(app, tmp_path, 2)
    rutas[0].write_bytes(b"esto no es una foto")
    problemas = app.publish_queue.missing_photos(None)
    assert [(p["nombre"], p["motivo"]) for p in problemas] == [("foto-0.jpg", "está dañada o no es una imagen")]


def test_con_no_repetir_fotos_una_foto_que_falta_se_salta_y_se_avisa(app, tmp_path):
    rutas = _fotos(app, tmp_path, 3)
    rutas[0].unlink()
    queue = app.publish_queue
    job = queue.enqueue_master(None, _refs(app)[:1], copies=2, generate_images=False)
    queue.run_until_idle()
    assert queue.progress(job).published == 2  # la cola no se bloquea
    avisos = [e for e in app.audit.recent(limit=40) if "no se puede subir" in e.action]
    assert len(avisos) == 1 and "foto-0.jpg" in (avisos[0].error or "")


def test_una_foto_que_wallapop_rechaza_se_aparta_y_la_cola_sigue(app, tmp_path):
    from lot_bot.publishing.service import PublishOutcome

    rutas = _fotos(app, tmp_path, 3)
    queue = app.publish_queue
    original = app.master_ads.publish_single
    usadas = []

    def publicar(key, ref, overrides, **kw):
        usadas.append(Path(kw["only_images"][0]).name)
        if kw["only_images"][0] == str(rutas[0]):
            return PublishOutcome(
                product_sku=None, account_ref=ref, success=False,
                message="NO se ha publicado: Wallapop no ha cargado la foto del anuncio "
                "(Wallapop ha rechazado la foto.).",
                error_code="ImageUploadError",
            )
        return original(key, ref, overrides, **kw)

    app.master_ads.publish_single = publicar
    job = queue.enqueue_master(None, _refs(app)[:1], copies=2, generate_images=False)
    queue.run_until_idle()
    progreso = queue.progress(job)
    assert progreso.published == 2 and progreso.failed == 0
    assert usadas == ["foto-0.jpg", "foto-1.jpg", "foto-2.jpg"]  # la mala solo una vez
    assert len(queue.rejected_photos()) == 1


# ===========================================================================
# 2. Anuncios sin confirmar: no solo por el título
# ===========================================================================
def _no_confirma(app, extra=None):
    """Wallapop publica el anuncio pero no lo confirma en pantalla. `extra`:
    otro anuncio que aparece a la vez en la cuenta (p. ej. subido a mano)."""
    service = app.wallapop
    original = service.create_item

    def crear(ref, draft):
        original(ref, draft)
        if extra is not None:
            original(ref, extra(draft))
        return OperationResult(False, "no confirmado", None, {"codigo": UNCONFIRMED_CODE})

    service.create_item = crear


def test_sin_confirmar_se_reconoce_por_titulo_y_precio(app_with_data):
    app = app_with_data
    queue = app.publish_queue
    from dataclasses import replace

    # A la vez aparece uno con el MISMO título pero OTRO precio: no se confunde.
    _no_confirma(app, extra=lambda d: replace(d, price=d.price + 50))
    job = queue.enqueue_master(None, _refs(app)[:1], copies=1, generate_images=False)
    queue.run_until_idle()
    tarea = queue.progress(job).tasks[0]
    assert tarea["estado"] == "published", tarea["error"]
    assert tarea["id_wallapop"]  # con la dirección del anuncio de verdad


def test_si_hay_dudas_queda_sin_confirmar_y_se_pide_revisarlo(app_with_data):
    app = app_with_data
    queue = app.publish_queue
    # A la vez aparece OTRO con el mismo título y el mismo precio (¿subido a mano?).
    _no_confirma(app, extra=lambda d: d)
    job = queue.enqueue_master(None, _refs(app)[:1], copies=1, generate_images=False)
    queue.run_until_idle()
    tarea = queue.progress(job).tasks[0]
    assert tarea["estado"] == "unconfirmed"
    assert "Comprobación manual" in tarea["error"]
    assert any("revisarlo a mano" in e.action for e in app.audit.recent(limit=30))


def test_si_no_aparece_queda_sin_confirmar(app_with_data):
    app = app_with_data
    queue = app.publish_queue
    service = app.wallapop
    service.create_item = lambda ref, draft: OperationResult(
        False, "no confirmado", None, {"codigo": UNCONFIRMED_CODE}
    )
    job = queue.enqueue_master(None, _refs(app)[:1], copies=1, generate_images=False)
    queue.run_until_idle()
    tarea = queue.progress(job).tasks[0]
    assert tarea["estado"] == "unconfirmed"
    assert "probablemente NO se publicó" in tarea["error"]


def test_los_anuncios_que_ya_estaban_no_cuentan_como_nuevos(app_with_data):
    """Lo que ya había en la cuenta al empezar (aunque tenga el mismo título y
    precio) no se toma por el anuncio que falta."""
    app = app_with_data
    queue = app.publish_queue
    ref = _refs(app)[0]
    # Ya había uno igual (publicado antes y conocido por LOT Bot).
    primero = queue.enqueue_master(None, [ref], copies=1, generate_images=False)
    queue.run_until_idle()
    assert queue.progress(primero).published == 1
    app.wallapop.create_item = lambda r, d: OperationResult(
        False, "no confirmado", None, {"codigo": UNCONFIRMED_CODE}
    )  # este NO se publica
    job = queue.enqueue_master(None, [ref], copies=1, generate_images=False)
    queue.run_until_idle()
    assert queue.progress(job).tasks[0]["estado"] == "unconfirmed"


def test_el_precio_esperado_se_guarda_en_cada_anuncio(app):
    job = app.publish_queue.enqueue_master(None, _refs(app)[:1], copies=1, start=False)
    with app.db.session_scope() as session:
        tarea = session.query(PublishTask).filter(PublishTask.job_id == job).one()
        assert tarea.payload["precio"] == app.master_ads.render(app.master_ads.get(None))["price"]
        assert session.get(PublishJob, job).parallel is False


def test_lo_interrumpido_al_cerrar_tambien_se_busca_por_titulo_y_precio(app_with_data):
    app = app_with_data
    queue = app.publish_queue
    job = queue.enqueue_master(None, _refs(app)[:1], copies=1, start=False)
    with app.db.session_scope() as session:
        tarea = session.query(PublishTask).filter(PublishTask.job_id == job).one()
        tarea.status = PublishTaskStatus.UNCONFIRMED
    assert queue._confirm_unconfirmed(job) == 0  # no está en Wallapop: no se inventa


def test_cancelar_a_la_vez_no_deja_anuncios_colgados(app_fichero, tmp_path):
    app = app_fichero
    _fotos(app, tmp_path, 8)
    queue = app.publish_queue
    original = app.master_ads.publish_single
    job = [None]

    def publicar(key, ref, overrides, **kw):
        resultado = original(key, ref, overrides, **kw)
        if queue.progress(job[0]).published == 2:
            queue.cancel(job[0])  # el usuario cancela con anuncios esperando
        return resultado

    app.master_ads.publish_single = publicar
    job[0] = queue.enqueue_master(None, _refs(app), copies=8, generate_images=False, parallel=True)
    queue.run_parallel_until_idle()
    estados = {t["estado"] for t in queue.progress(job[0]).tasks}
    assert estados <= {"published", "cancelled"}, estados
    assert not queue._lanes_alive()


def test_anuncios_en_curso_sin_hilo_se_recuperan_sin_duplicar(app_fichero):
    app = app_fichero
    queue = app.publish_queue
    refs = _refs(app)
    job = queue.enqueue_master(None, refs[:2], copies=2, generate_images=False, parallel=True,
                               start=False)
    with app.db.session_scope() as session:
        tareas = session.query(PublishTask).filter(PublishTask.job_id == job).order_by(PublishTask.position).all()
        tareas[0].status = PublishTaskStatus.PUBLISHING  # su hilo falló a mitad
        tareas[1].status = PublishTaskStatus.WAITING
    queue.start(job)
    queue.run_once()
    progreso = queue.progress(job)
    assert [t["estado"] for t in progreso.tasks] == ["unconfirmed", "pending"]
