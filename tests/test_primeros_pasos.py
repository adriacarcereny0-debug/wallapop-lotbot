"""Guía «Primeros pasos»: los pasos se marcan solos según el estado real."""

from __future__ import annotations

import pytest

from lot_bot.ui.onboarding import onboarding_steps, remember_choice, should_show_at_start


def test_en_demo_licencia_y_cuentas_ya_cuentan_como_hechas(app):
    steps = onboarding_steps(app)
    assert [s.title for s in steps][:2] == ["Licencia", "Conecta tu cuenta de Wallapop"]
    assert steps[0].done and steps[1].done
    assert len(steps) == 5


def test_publicar_se_marca_al_publicar(app):
    from lot_bot.publishing.queue import FakeClock

    assert not onboarding_steps(app)[-1].done
    refs = [a.internal_ref for a in app.accounts.list_accounts() if a.is_connected][:1]
    app.publish_queue.clock = FakeClock()
    app.publish_queue.enqueue_master(None, refs, copies=1, generate_images=False)
    app.publish_queue.run_until_idle()
    assert onboarding_steps(app)[-1].done


def test_se_muestra_al_abrir_hasta_que_se_quita(app):
    assert should_show_at_start(app)  # falta publicar
    remember_choice(app, True)
    assert not should_show_at_start(app)


def test_sin_licencia_en_wallapop_real_el_primer_paso_esta_pendiente(app, temp_paths):
    from lot_bot.licensing.config import LicenseConfig
    from lot_bot.licensing.manager import LicenseManager

    app.backend.demo = False
    app.license = LicenseManager(temp_paths.config, config=LicenseConfig("https://x", (b"x" * 32,)))
    step = onboarding_steps(app)[0]
    assert step.title == "Activa tu licencia" and not step.done
    assert (step.section, step.tab) == ("Configuración", "Licencia")


@pytest.mark.ui
def test_la_guia_abre_la_pantalla_de_cada_paso(app, qtbot):
    from lot_bot.ui.main_window import MainWindow
    from lot_bot.ui.onboarding import OnboardingDialog

    window = MainWindow(app)
    qtbot.addWidget(window)
    window.open_section("Configuración", "Licencia")
    view = window.views[window.stack.currentIndex()]
    assert type(view).__name__ == "SettingsView"
    assert view.tabs.tabText(view.tabs.currentIndex()) == "Licencia"
    dialog = OnboardingDialog(app, window.open_section, window)
    qtbot.addWidget(dialog)
    from PySide6.QtWidgets import QPushButton

    step_buttons = [b for b in dialog.findChildren(QPushButton) if b.text() in ("Ir", "Hecho")]
    assert len(step_buttons) == 5
    assert sum(1 for b in step_buttons if b.text() == "Hecho") == sum(1 for s in onboarding_steps(app) if s.done)
