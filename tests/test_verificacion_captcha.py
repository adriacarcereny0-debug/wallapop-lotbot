"""Verificaciones de Wallapop (CAPTCHA): las completa SIEMPRE la persona.

Lo que hace LOT Bot para que no se pare la publicación automática:

* pone delante la ventana de la cuenta y avisa (franja, sonido, notificación);
* en cuanto la verificación desaparece, sigue SOLO desde el mismo paso;
* espera lo que haga falta (sin límite de tiempo);
* mientras tanto, si hay anuncios de OTRAS cuentas, los sigue publicando;
  el de la cuenta con verificación se hace después (y nunca si ya se había
  pulsado «Publicar»: así no se puede duplicar).
"""

from __future__ import annotations

import threading
import time

import pytest

from lot_bot.database.models import PublishJobStatus
from lot_bot.publishing.queue import GATE_DEFER, VERIFICATION_CODE
from lot_bot.wallapop.auth.base import AuthCredential, AuthKind
from lot_bot.wallapop.errors import VerificationDeferredError, VerificationRequiredError
from tests.test_browser_integration import FORM, SITE, FakeLauncher, draft, make_service, profiles  # noqa: F401
from tests.test_guided_flow import real  # noqa: F401  (fixture)
from tests.test_publish_flow import database, esperar, listo  # noqa: F401  (fixtures)


# ---------------------------------------------------------------------------
# Formulario: nunca toca la verificación; pregunta y sigue cuando desaparece
# ---------------------------------------------------------------------------
def test_el_formulario_pasa_como_saber_si_la_verificacion_ya_no_esta(profiles, tmp_path):  # noqa: F811
    world = {"logged_in": True, "item_url": "https://es.wallapop.com/item/c-9"}
    service, launcher = make_service(profiles, world, tmp_path)
    vistos = []

    def gate(ref, mensaje, *, solved=None, can_defer=False, **_):
        page = launcher.pages[0]
        vistos.append((can_defer, solved()))  # aún está: no resuelta
        world["verification"] = False  # la persona la completa
        vistos.append((can_defer, solved()))
        assert not any(e[0] in ("fill", "click", "option") and e[-1] == SITE.verification[0]
                       for e in page.log)
        return True

    service.user_gate = gate
    world["verification"] = True
    result = service.create_item("acc-1", draft(tmp_path))
    assert result.success
    assert vistos == [(True, False), (True, True)]
    assert ("focus",) in launcher.pages[0].log  # ventana delante


def test_tras_pulsar_publicar_nunca_se_aplaza_el_anuncio(profiles, tmp_path):  # noqa: F811
    """Si el CAPTCHA sale DESPUÉS de «Publicar», se espera ahí mismo: hacer el
    anuncio otra vez podría duplicarlo."""
    world = {"logged_in": True, "item_url": "https://es.wallapop.com/item/c-9"}
    service, launcher = make_service(profiles, world, tmp_path)
    permisos = []

    def gate(ref, mensaje, *, solved=None, can_defer=False, **_):
        permisos.append(can_defer)
        world["verification"] = False
        return GATE_DEFER  # aunque lo pida, después de «Publicar» no se aplaza

    service.user_gate = gate
    from tests.test_browser_integration import FakePage

    original_click = FakePage.click

    def click_y_captcha(self, target):
        original_click(self, target)
        if target in FORM.submit.targets:
            world["verification"] = True

    FakePage.click = click_y_captcha
    try:
        result = service.create_item("acc-1", draft(tmp_path))
    finally:
        FakePage.click = original_click
    assert result.success
    assert permisos == [False]
    assert world["submits"] == 1  # nunca se ha vuelto a publicar


def test_antes_de_publicar_el_anuncio_se_puede_aplazar(profiles, tmp_path):  # noqa: F811
    world = {"logged_in": True, "verification": True}
    service, launcher = make_service(profiles, world, tmp_path)
    service.user_gate = lambda ref, mensaje, **kw: GATE_DEFER if kw.get("can_defer") else True
    with pytest.raises(VerificationDeferredError):
        service.create_item("acc-1", draft(tmp_path))
    assert world.get("submits") is None
    assert service.pool.is_open("acc-1")  # la ventana se queda con el CAPTCHA
    assert service.verification_pending("acc-1") is True
    world["verification"] = False
    assert service.verification_pending("acc-1") is False
    assert service.verification_pending("otra") is None  # nunca abre una ventana


def test_sin_nadie_que_responda_se_sigue_parando_como_antes(profiles, tmp_path):  # noqa: F811
    world = {"logged_in": True, "verification": True}
    service, _ = make_service(profiles, world, tmp_path)
    with pytest.raises(VerificationRequiredError) as info:
        service.create_item("acc-1", draft(tmp_path))
    assert not isinstance(info.value, VerificationDeferredError)


# ---------------------------------------------------------------------------
# Esperar a la persona no cuenta como «el navegador no responde»
# ---------------------------------------------------------------------------
def test_esperar_a_la_persona_no_cierra_el_navegador(tmp_path):
    from lot_bot.wallapop.browser.driver import BrowserUnavailable
    from lot_bot.wallapop.browser.pool import BrowserSessionPool

    pool = BrowserSessionPool(FakeLauncher({}))
    opciones = {"visible": False, "channels": ["chromium"], "locale": "es-ES"}

    def persona_tarda(page):
        with pool.waiting_for_user("acc-1"):
            time.sleep(1.5)
        return "hecho"

    assert pool.run("acc-1", tmp_path / "acc-1", persona_tarda, timeout=0.5, **opciones) == "hecho"
    bloqueo = threading.Event()
    with pytest.raises(BrowserUnavailable):  # colgado de verdad: sí se corta
        pool.run("acc-2", tmp_path / "acc-2", lambda page: bloqueo.wait(10), timeout=0.3, **opciones)
    bloqueo.set()


def test_sin_limite_de_tiempo_esperando_la_verificacion():
    from lot_bot.publishing import queue
    from lot_bot.wallapop.browser.form import ListingForm

    assert queue.USER_GATE_TIMEOUT_S is None
    assert ListingForm.__init__.__kwdefaults__["gate_timeout_s"] is None


# ---------------------------------------------------------------------------
# Cola con varias cuentas: las demás siguen publicando
# ---------------------------------------------------------------------------
def otra_cuenta(app, alias="Otra tienda"):
    cuenta = app.accounts.add_account(alias)
    app.wallapop.profiles.profile_dir(cuenta.internal_ref).joinpath("Local State").write_text("{}")
    app.accounts.store_credential(
        cuenta.internal_ref,
        AuthCredential(kind=AuthKind.BROWSER_SESSION, metadata={"account_ref": cuenta.internal_ref}),
    )
    return cuenta


def hasta_terminar(cola, job, segundos=40.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if cola._job_status(job) in (PublishJobStatus.COMPLETED, PublishJobStatus.CANCELLED):
            return
        if not cola.run_once():
            time.sleep(0.05)


def test_captcha_en_una_cuenta_las_demas_siguen_publicando(listo):  # noqa: F811
    app, world, cuenta_a = listo
    cuenta_b = otra_cuenta(app)
    a, b = cuenta_a.internal_ref, cuenta_b.internal_ref
    world["verification_profiles"] = {a}  # Wallapop pide CAPTCHA solo en A
    cola = app.publish_queue
    estados = []
    cola.listeners.append(lambda job_id: estados.append(cola._job_status(job_id)))
    job = cola.enqueue_master(None, [a, b], copies=4, generate_images=False)
    hilo = threading.Thread(target=hasta_terminar, args=(cola, job), daemon=True)
    hilo.start()

    def solo_falta_a():
        p = cola.progress(job)
        return sum(1 for t in p.tasks if t["cuenta_ref"] == b and t["estado"] == "published") == 2

    assert esperar(solo_falta_a, 30)
    progreso = cola.progress(job)
    assert progreso.status == "running"  # nunca se ha parado la cola
    pendientes_a = [t for t in progreso.tasks if t["cuenta_ref"] == a]
    assert all(t["estado"] == "pending" for t in pendientes_a)
    assert any(t["codigo_error"] == VERIFICATION_CODE for t in pendientes_a)
    aviso = cola.pending_verifications()
    assert [(v["cuenta"], v["aplazada"]) for v in aviso] == [("Mi tienda", True)]

    world["verification_profiles"] = set()  # la persona completa el CAPTCHA en A
    hilo.join(40)
    progreso = cola.progress(job)
    assert progreso.status == "completed", progreso.tasks
    assert progreso.published == 4 and progreso.failed == 0
    assert PublishJobStatus.PAUSED not in estados  # nunca ha pedido «Continuar»
    assert cola.pending_verifications() == []
    assert all(t["intentos"] == 1 for t in progreso.tasks)  # aplazar no cuenta como intento
    assert all(t["error"] is None for t in progreso.tasks)


def test_si_la_cuenta_con_captcha_es_la_unica_se_espera_y_sigue_sola(listo):  # noqa: F811
    """Con una sola cuenta no hay a dónde ir: se espera en el mismo paso."""
    app, world, cuenta = listo
    world["verification_profiles"] = {cuenta.internal_ref}
    cola = app.publish_queue
    job = cola.enqueue_master(None, [cuenta.internal_ref], copies=2, generate_images=False)
    hilo = threading.Thread(target=hasta_terminar, args=(cola, job), daemon=True)
    hilo.start()
    assert esperar(lambda: cola.progress(job).status == "paused")
    assert [v["aplazada"] for v in cola.pending_verifications()] == [False]
    pagina = world["pages"][0]
    antes = pagina.log.count(("focus",))
    cola.show_verification_window(cuenta.internal_ref)  # botón del aviso
    assert esperar(lambda: pagina.log.count(("focus",)) == antes + 1)
    world["verification_profiles"] = set()
    hilo.join(40)
    assert cola.progress(job).published == 2
    assert world["pages"][0].log.count(("goto", SITE.url("subir"))) >= 2


def test_cancelar_la_cola_olvida_las_verificaciones(listo):  # noqa: F811
    app, world, cuenta_a = listo
    cuenta_b = otra_cuenta(app)
    world["verification_profiles"] = {cuenta_a.internal_ref}
    cola = app.publish_queue
    job = cola.enqueue_master(
        None, [cuenta_a.internal_ref, cuenta_b.internal_ref], copies=2, generate_images=False
    )
    cola.run_once()
    assert cola.pending_verifications()
    cola.cancel(job)
    assert cola.pending_verifications() == []


# ---------------------------------------------------------------------------
# Aviso en LOT Bot: franja en todas las pantallas, sonido y notificación
# ---------------------------------------------------------------------------
@pytest.mark.ui
def test_la_franja_de_aviso_aparece_suena_y_se_quita_sola(app_with_data, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from lot_bot.ui import verification_alert
    from lot_bot.ui.main_window import MainWindow

    qt = QApplication.instance() or QApplication([])
    sonidos = []
    monkeypatch.setattr(verification_alert, "play_alert_sound", lambda: sonidos.append(1))
    ventana = MainWindow(app_with_data)
    aviso = ventana.verification_alert
    cola = app_with_data.publish_queue
    ref = app_with_data.accounts.list_accounts()[0].internal_ref
    aviso.check()
    assert aviso.isHidden() and sonidos == []

    cola._verification_started(ref, 1, deferred=True)
    aviso.check()
    qt.processEvents()
    assert not aviso.isHidden()
    texto = aviso.label.text()
    assert "Wallapop pide una verificación" in texto and "sigue solo" in texto
    assert "demás cuentas" in texto
    assert sonidos == [1]
    aviso.check()
    assert sonidos == [1]  # no suena en cada segundo

    cola._verification_cleared(ref)
    aviso.check()
    assert aviso.isHidden()
    ventana.close()
