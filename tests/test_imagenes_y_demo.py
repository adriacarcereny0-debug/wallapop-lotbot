"""Imágenes solo subidas desde el ordenador (sin IA) y anuncios de prueba
que se quitan al momento."""

from __future__ import annotations

import os

import pytest

from lot_bot.publishing.listings import ListingFilter


def textos(respuesta) -> str:
    return " ".join(m.text for m in respuesta.messages)


# ---------------------------------------------------------------------------
# Imágenes: sin IA
# ---------------------------------------------------------------------------
def test_la_cola_nunca_genera_imagenes_aunque_estuviera_activado(app):
    from lot_bot.database.models import Setting

    with app.db.session_scope() as session:  # configuración antigua
        session.merge(Setting(key="publicacion", value={"generate_images": True}))
    assert app.publish_queue.settings()["generate_images"] is False
    assert app.publish_queue.save_settings(generate_images=True)["generate_images"] is False


@pytest.mark.parametrize(
    "orden",
    ["Genera una imagen del canapé", "Mejora la imagen 3", "Cambia el estilo de la imagen 2"],
)
def test_el_asistente_explica_que_ya_no_crea_imagenes(app, orden):
    r = app.agent.ask(orden)
    texto = textos(r)
    assert "ya no crea ni edita imágenes con IA" in texto
    assert not r.needs_confirmation


def test_el_asistente_no_tiene_herramientas_de_imagenes_con_ia(app):
    nombres = {t.name for t in app.agent.registry.list_tools()} if hasattr(
        app.agent, "registry"
    ) else set()
    from lot_bot.ai.tools.image_tools import IMAGE_TOOLS

    assert [t.name for t in IMAGE_TOOLS] == ["list_images"]
    assert not nombres & {"generate_image", "change_image_style", "change_image_room"}


@pytest.mark.ui
def test_la_pantalla_imagenes_solo_sube_fotos(app_with_data):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from lot_bot.ui.main_window import NAVIGATION
    from lot_bot.ui.views.image_studio import ImageStudioView
    from lot_bot.ui.views.settings import SettingsView
    from lot_bot.ui.widgets.workers import TaskRunner

    QApplication.instance() or QApplication([])
    vista = ImageStudioView(app_with_data, TaskRunner(1))
    vista.refresh()
    botones = {b.text() for b in vista.findChildren(QPushButton)}
    assert "Subir fotos…" in botones and "Usar en mis anuncios" in botones
    assert not {"Generar", "Cambiar estilo", "Cambiar habitación"} & botones
    assert vista.title == "Imágenes"
    assert ("Imágenes", "imagenes") in [(n, i) for n, i, _ in NAVIGATION]

    ajustes = SettingsView(app_with_data, TaskRunner(1))
    opciones = [ajustes.publish_images.itemText(i) for i in range(ajustes.publish_images.count())]
    assert len(opciones) == 2 and not any("FLUX" in o for o in opciones)
    pestañas = [ajustes.tabs.tabText(i) for i in range(ajustes.tabs.count())]
    assert "IA / Imágenes" not in pestañas


# ---------------------------------------------------------------------------
# Anuncios de prueba (cuentas DEMO): se quitan al momento
# ---------------------------------------------------------------------------
def _activos(app, n=3):
    app.listings.sync_all([a.internal_ref for a in app.accounts.list_accounts()])
    return [v for v in app.listings.search(ListingFilter(limit=100)) if v.status == "active"][:n]


def test_en_modo_demo_se_borran_sin_esperar(app):
    vistos = _activos(app)
    esperas = []
    salida = app.publishing.delete_listings(
        [v.id for v in vistos], confirmed=True, sleep=esperas.append
    )
    assert all(o.success for o in salida) and esperas == []


def test_en_modo_real_los_de_cuentas_demo_se_quitan_sin_tocar_wallapop(app, monkeypatch):
    from lot_bot.wallapop.browser.driver import PlaywrightLauncher

    vistos = _activos(app)
    monkeypatch.setattr(PlaywrightLauncher, "available", lambda self: (True, ""))
    app.set_integration_mode("navegador")
    assert not getattr(app.wallapop, "is_mock", False)

    def prohibido(*a, **k):
        raise AssertionError("No se debe abrir el navegador para un anuncio de prueba")

    monkeypatch.setattr(app.wallapop, "delete_item", prohibido)
    monkeypatch.setattr(app.wallapop, "list_items", prohibido)
    esperas = []
    salida = app.publishing.delete_listings(
        [v.id for v in vistos], confirmed=True, sleep=esperas.append
    )
    assert all(o.success for o in salida), [o.message for o in salida]
    assert esperas == []
    assert all(app.listings.get(v.id).status == "removed" for v in vistos)
