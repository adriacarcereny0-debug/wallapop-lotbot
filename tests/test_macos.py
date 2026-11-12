"""Versión para Mac: rutas del .app empaquetado y textos de la interfaz."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lot_bot.config import paths

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Simula rutas POSIX de macOS (/Applications); en Windows serían D:\\... "
    "Se ejecuta en el CI de Mac.",
)
def test_app_dir_en_el_app_de_mac_es_la_carpeta_que_lo_contiene(monkeypatch):
    exe = "/Applications/LOT Bot.app/Contents/MacOS/LOT-Bot"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.app_dir() == Path("/Applications")


def test_datos_del_usuario_en_mac(monkeypatch):
    monkeypatch.delenv("LOT_BOT_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths._default_user_root() == Path.home() / "Library" / "Application Support" / "LOT Bot"


def test_recursos_de_empaquetado_para_mac():
    assert (ROOT / "lot_bot" / "resources" / "lot_bot.icns").is_file()
    spec = (ROOT / "build" / "LOT-Bot.spec").read_text(encoding="utf-8")
    assert "BUNDLE(" in spec and "LOT Bot.app" in spec
    for script in ("build/build_macos.sh", "iniciar_lot_bot_mac.command", "compilar_app_mac.command"):
        path = ROOT / script
        assert path.is_file(), script
        assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
