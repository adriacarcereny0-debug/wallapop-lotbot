"""Ritmo por cuenta: menos visitas seguidas a Wallapop = menos verificaciones.

Sin trucos para ocultar el bot: solo se publica más espaciado, como un
vendedor normal, y no se hacen lecturas extra entre anuncio y anuncio.
Se usa el reloj simulado (no se espera de verdad).
"""

from __future__ import annotations

import pytest

from lot_bot.publishing.queue import (
    DEFAULT_PUBLISH_SETTINGS,
    SLOWDOWN_FACTOR,
    UNCONFIRMED_CODE,
)
from lot_bot.wallapop.dto import OperationResult


def refs(app, n=None):
    cuentas = [a.internal_ref for a in app.accounts.list_accounts() if a.is_connected]
    return cuentas[:n] if n else cuentas


def horas_por_cuenta(progress):
    out: dict[str, list] = {}
    for t in sorted(progress.tasks, key=lambda t: t["inicio"]):
        out.setdefault(t["cuenta_ref"], []).append(t["inicio"])
    return out


def separaciones(horas):
    return [(b - a).total_seconds() for a, b in zip(horas, horas[1:], strict=False)]


def test_valores_por_defecto():
    assert DEFAULT_PUBLISH_SETTINGS["account_interval_seconds"] == 300
    assert DEFAULT_PUBLISH_SETTINGS["batch_size"] == 10
    assert DEFAULT_PUBLISH_SETTINGS["batch_rest_minutes"] == 20
    assert DEFAULT_PUBLISH_SETTINGS["slowdown_hours"] == 3
    assert SLOWDOWN_FACTOR == 2


def test_los_ajustes_fuera_de_rango_se_corrigen(app):
    queue = app.publish_queue
    ajustes = queue.save_settings(
        account_interval_seconds=5, batch_size=-3, batch_rest_minutes=99999, slowdown_hours="x"
    )
    assert ajustes["account_interval_seconds"] == 60  # nunca menos que el mínimo general
    assert ajustes["batch_size"] == 0
    assert ajustes["batch_rest_minutes"] == 600
    assert ajustes["slowdown_hours"] == 3  # valor no válido: el de siempre


def test_una_sola_cuenta_espera_su_intervalo_entre_anuncios(app):
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app, 1), copies=3, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 3
    (horas,) = horas_por_cuenta(progress).values()
    assert all(s >= 300 for s in separaciones(horas))


def test_con_varias_cuentas_se_alternan_y_no_se_pierde_velocidad(app):
    queue = app.publish_queue
    cuentas = refs(app, 2)
    job = queue.enqueue_master(None, cuentas, copies=6, generate_images=False)
    inicio = queue.clock.now()
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 6
    for horas in horas_por_cuenta(progress).values():
        assert all(s >= 300 for s in separaciones(horas))  # cada cuenta, a su ritmo
    todas = sorted(t["inicio"] for t in progress.tasks)
    assert all(s >= 60 for s in separaciones(todas))  # y el mínimo general se respeta
    # 3 por cuenta a 5 min = ~10 min en total (no 6 × 5 min = 25 min).
    assert queue.clock.now() - inicio <= 2 * 300 + 120


def test_tras_varios_seguidos_la_cuenta_descansa(app):
    queue = app.publish_queue
    queue.save_settings(batch_size=2, batch_rest_minutes=20)
    job = queue.enqueue_master(None, refs(app, 1), copies=3, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 3
    (horas,) = horas_por_cuenta(progress).values()
    primera, segunda = separaciones(horas)
    assert 300 <= primera < 20 * 60
    assert segunda >= 20 * 60  # descanso tras 2 seguidos


def test_mientras_una_cuenta_descansa_las_demas_siguen(app):
    queue = app.publish_queue
    queue.save_settings(batch_size=1, batch_rest_minutes=60, account_interval_seconds=60)
    a, b = refs(app, 2)
    job = queue.enqueue_master(None, [a, a, b], copies=3, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.published == 3
    orden = [t["cuenta_ref"] for t in sorted(progress.tasks, key=lambda t: t["inicio"])]
    assert orden[:2] == [a, b]  # A descansa: se publica en B sin esperar a A
    assert any("descansa" in nota for nota in queue.pacing_notes())


def test_tras_una_verificacion_la_cuenta_va_mas_despacio(app):
    queue = app.publish_queue
    (cuenta,) = refs(app, 1)
    queue._slow_down(cuenta)  # Wallapop acaba de pedir una verificación
    assert any("más despacio" in nota for nota in queue.pacing_notes())
    job = queue.enqueue_master(None, [cuenta], copies=2, generate_images=False)
    queue.run_until_idle()
    (horas,) = horas_por_cuenta(queue.progress(job)).values()
    assert separaciones(horas)[0] >= 300 * SLOWDOWN_FACTOR


def test_ir_mas_despacio_se_puede_desactivar(app):
    queue = app.publish_queue
    queue.save_settings(slowdown_hours=0)
    (cuenta,) = refs(app, 1)
    queue._slow_down(cuenta)
    assert queue.pacing_notes() == []


def test_la_verificacion_activa_ir_mas_despacio(app, monkeypatch):
    from lot_bot.wallapop.errors import VerificationRequiredError

    def verificacion(ref, draft):
        raise VerificationRequiredError("captcha")

    monkeypatch.setattr(app.wallapop, "create_item", verificacion)
    queue = app.publish_queue
    queue.enqueue_master(None, refs(app, 1), copies=1, generate_images=False)
    queue.run_until_idle()
    assert any("más despacio" in nota for nota in queue.pacing_notes())


# ---------------------------------------------------------------------------
# Sin lecturas de «Tus productos» entre anuncio y anuncio
# ---------------------------------------------------------------------------
def test_los_no_confirmados_se_comprueban_al_final_de_la_cola(app, monkeypatch):
    service = app.wallapop
    original = service.create_item
    llamadas = {"n": 0}

    def sin_confirmar_el_primero(ref, draft):
        llamadas["n"] += 1
        result = original(ref, draft)  # Wallapop SÍ lo publica...
        if llamadas["n"] == 1:  # ...pero no lo confirma en pantalla
            return OperationResult(False, "no confirmado", None, {"codigo": UNCONFIRMED_CODE})
        return result

    monkeypatch.setattr(service, "create_item", sin_confirmar_el_primero)
    queue = app.publish_queue
    lecturas_en_medio = []
    original_check = queue._confirm_unconfirmed
    monkeypatch.setattr(
        queue, "_confirm_unconfirmed",
        lambda job_id, account_ref=None: (
            lecturas_en_medio.append(account_ref) if account_ref else None
        ) or original_check(job_id, account_ref),
    )
    job = queue.enqueue_master(None, refs(app, 2), copies=3, generate_images=False)
    queue.run_once()
    assert queue.progress(job).tasks[0]["estado"] == "unconfirmed"
    queue.run_until_idle()
    progress = queue.progress(job)
    assert lecturas_en_medio == []  # nada entre anuncio y anuncio
    assert progress.status == "completed"
    assert progress.published == 3  # el primero se encontró en «Tus productos» al final
    assert progress.tasks[0]["estado"] == "published"


def test_varios_sin_confirmar_seguidos_se_miran_antes_de_pausar(app, monkeypatch):
    """Si Wallapop deja de confirmar TODOS (p. ej. cambia la página final),
    antes de pausar la cola se mira «Tus productos»: si están, se sigue."""
    service = app.wallapop
    original = service.create_item

    def nunca_confirma(ref, draft):
        original(ref, draft)
        return OperationResult(False, "no confirmado", None, {"codigo": UNCONFIRMED_CODE})

    monkeypatch.setattr(service, "create_item", nunca_confirma)
    queue = app.publish_queue
    job = queue.enqueue_master(None, refs(app, 2), copies=4, generate_images=False)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "completed", progress.pause_reason
    assert progress.published == 4


@pytest.mark.parametrize("ocupada", [True, False])
def test_la_sincronizacion_programada_espera_si_hay_una_cola(app, monkeypatch, ocupada):
    ejecutadas = []
    monkeypatch.setattr(app.listings, "sync_all", lambda refs: ejecutadas.append(refs) or {})
    monkeypatch.setattr(app.publish_queue, "is_publishing", lambda: ocupada)
    resultado = app.automations.run_scheduled("sync_listings")
    assert resultado.ok
    if ocupada:
        assert ejecutadas == [] and "Aplazada" in resultado.summary
    else:
        assert len(ejecutadas) == 1
    # Ejecutarla a mano (botón) funciona siempre.
    app.automations.run_now("sync_listings")
    assert len(ejecutadas) == (1 if ocupada else 2)


def test_tus_productos_se_lee_al_empezar_en_todas_las_cuentas(app, monkeypatch):
    queue = app.publish_queue
    queue.save_settings(max_listings_per_account=500)
    leidas = []
    original = app.listings.sync_account
    monkeypatch.setattr(
        app.listings, "sync_account", lambda ref: leidas.append(ref) or original(ref)
    )
    cuentas = refs(app, 3)
    job = queue.enqueue_master(None, cuentas, copies=3, generate_images=False)
    queue.run_once()  # primer anuncio
    assert sorted(leidas) == sorted(cuentas)  # todas al empezar
    queue.run_until_idle()
    assert sorted(leidas) == sorted(cuentas)  # y ninguna más entre anuncios
    assert queue.progress(job).published == 3
