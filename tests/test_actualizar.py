"""Actualizar LOT Bot con un clic desde GitHub: se prueba con repositorios
git de verdad (un «GitHub» local, tu copia y la del cliente)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lot_bot.core.updater import Updater, find_git

pytestmark = pytest.mark.skipif(find_git() is None, reason="git no está instalado")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repos(tmp_path):
    """«github» (remoto), «tu» copia (donde haces cambios) y la del cliente."""
    remoto = tmp_path / "github.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remoto))
    tu = tmp_path / "tu"
    git(tmp_path, "clone", str(remoto), str(tu))
    for repo in (tu,):
        git(repo, "config", "user.email", "dev@example.com")
        git(repo, "config", "user.name", "Dev")
    (tu / "lot_bot.txt").write_text("versión 1\n")
    (tu / "requirements.txt").write_text("PySide6\n")
    git(tu, "add", ".")
    git(tu, "commit", "-m", "Primera versión")
    git(tu, "push", "-u", "origin", "main")
    cliente = tmp_path / "cliente"
    git(tmp_path, "clone", str(remoto), str(cliente))
    git(cliente, "config", "user.email", "cliente@example.com")
    git(cliente, "config", "user.name", "Cliente")
    return tu, cliente, tmp_path


def publicar(tu: Path, fichero: str, texto: str, mensaje: str) -> None:
    (tu / fichero).write_text(texto)
    git(tu, "add", ".")
    git(tu, "commit", "-m", mensaje)
    git(tu, "push")


def updater(cliente: Path, tmp_path: Path, **kw) -> Updater:
    return Updater(cliente, tmp_path / "datos" / "actualizacion.json", **kw)


def test_al_dia_no_hay_nada(repos):
    _tu, cliente, tmp = repos
    info = updater(cliente, tmp).check()
    assert not info.available and "al día" in info.message


def test_ve_los_cambios_y_actualiza_con_un_clic(repos):
    tu, cliente, tmp = repos
    publicar(tu, "lot_bot.txt", "versión 2\n", "Chat del asistente con aspecto de chat de verdad")
    publicar(tu, "otro.txt", "x\n", "Interruptor para no repetir fotos")
    up = updater(cliente, tmp)
    info = up.check()
    assert info.available and info.behind == 2 and info.branch == "main"
    assert info.changes == ["Interruptor para no repetir fotos", "Chat del asistente con aspecto de chat de verdad"]
    assert not info.requirements_changed
    assert (cliente / "lot_bot.txt").read_text() == "versión 1\n"  # comprobar no cambia nada

    resultado = up.apply()
    assert resultado.ok, resultado.message
    assert (cliente / "lot_bot.txt").read_text() == "versión 2\n"
    assert not up.check().available
    assert up.previous_version() == resultado.previous


def test_si_cambian_los_componentes_se_instalan(repos):
    tu, cliente, tmp = repos
    publicar(tu, "requirements.txt", "PySide6\nnuevo-componente\n", "Componente nuevo")
    llamadas = []

    def run(cmd, **kw):
        if "pip" in cmd:
            llamadas.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.run(cmd, **kw)

    up = updater(cliente, tmp, run=run, python="python-del-cliente")
    assert up.check().requirements_changed
    resultado = up.apply()
    assert resultado.ok and resultado.requirements_installed
    assert llamadas and llamadas[0][:4] == ["python-del-cliente", "-m", "pip", "install"]


def test_los_cambios_a_mano_del_cliente_no_se_pierden(repos):
    tu, cliente, tmp = repos
    publicar(tu, "otro.txt", "x\n", "Arreglo")
    (cliente / "lot_bot.txt").write_text("tocado a mano\n")
    resultado = updater(cliente, tmp).apply()
    assert resultado.ok
    assert "cambios locales" in git(cliente, "stash", "list")  # guardados, no borrados


def test_volver_a_la_version_anterior(repos):
    tu, cliente, tmp = repos
    publicar(tu, "lot_bot.txt", "versión 2\n", "Versión 2")
    up = updater(cliente, tmp)
    up.apply()
    resultado = up.rollback()
    assert resultado.ok
    assert (cliente / "lot_bot.txt").read_text() == "versión 1\n"
    assert up.previous_version() is None
    assert up.check().available  # la nueva sigue disponible para cuando quiera


def test_sin_internet_o_sin_acceso_lo_explica(repos):
    _tu, cliente, tmp = repos
    git(cliente, "remote", "set-url", "origin", str(tmp / "no-existe.git"))
    info = updater(cliente, tmp).check()
    assert not info.available and "No se ha podido consultar GitHub" in info.message


def test_una_instalacion_que_no_es_de_github(tmp_path):
    up = updater(tmp_path, tmp_path)
    assert not up.supported
    assert not up.check().available
    assert "a mano" in up.unsupported_reason()


@pytest.mark.ui
def test_no_actualiza_con_una_cola_publicando(app_with_data, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from lot_bot.ui import update_banner

    QApplication.instance() or QApplication([])
    errores = []
    monkeypatch.setattr(update_banner, "show_error", lambda *a, **k: errores.append(a[1]))
    monkeypatch.setattr(app_with_data.publish_queue, "is_publishing", lambda: True)

    class Runner:
        def run(self, *a, **k):
            raise AssertionError("no debe actualizar")

    control = update_banner.UpdateController(app_with_data, Runner(), QWidget())
    control.update()
    assert errores and "cola publicando" in errores[0]


def test_si_existe_el_canal_estable_solo_llega_lo_publicado_ahi(repos):
    """Con una rama «estable», lo que subes a tu rama de trabajo NO llega a
    los clientes hasta que lo publicas en «estable»."""
    tu, cliente, tmp = repos
    git(tu, "push", "origin", "main:estable")  # canal creado (misma versión)
    publicar(tu, "lot_bot.txt", "en pruebas\n", "Cambio aún en pruebas")
    up = updater(cliente, tmp)
    assert not up.check().available  # el cambio en pruebas no se ofrece
    git(tu, "push", "origin", "main:estable")  # ahora sí: publicado
    info = up.check()
    assert info.available and info.branch == "estable"
    assert up.apply().ok
    assert (cliente / "lot_bot.txt").read_text() == "en pruebas\n"
