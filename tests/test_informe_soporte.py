"""«Enviar informe a soporte»: un .zip con registros, capturas e historial,
y nunca contraseñas, cookies, claves ni la base de datos."""

from __future__ import annotations

import os
import zipfile

from lot_bot.core.support_report import build_report
from lot_bot.logs.redaction import register_secret


def test_el_informe_lleva_lo_necesario_y_nada_privado(app_with_data, tmp_path):
    app = app_with_data
    logs = app.paths.logs
    logs.mkdir(parents=True, exist_ok=True)
    register_secret("clave-super-secreta-123")
    (logs / "lot_bot.log").write_text(
        "INFO arranque\nERROR algo falló con clave-super-secreta-123 y Bearer abcdefghijklmnop\n",
        encoding="utf-8",
    )
    nav = logs / "navegador"
    nav.mkdir(exist_ok=True)
    (nav / "20261108-Precio.png").write_bytes(b"\x89PNG captura")
    (nav / "20261108-Precio.json").write_text('{"paso": "Precio", "access_token": "xyz123456"}')
    (logs / "copia.db").write_bytes(b"base de datos")
    viejo = nav / "antiguo.png"
    viejo.write_bytes(b"\x89PNG viejo")
    os.utime(viejo, (0, 0))  # de hace años: no entra

    zip_path = build_report(app, "Se para al publicar el tercer anuncio", tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        nombres = set(zf.namelist())
        assert {"LEEME.txt", "sistema.txt", "historial.txt", "logs/lot_bot.log"} <= nombres
        assert "navegador/20261108-Precio.png" in nombres and "navegador/20261108-Precio.json" in nombres
        assert "navegador/antiguo.png" not in nombres
        assert not any(n.endswith(".db") for n in nombres)
        todo = "".join(zf.read(n).decode("utf-8", "replace") for n in nombres if not n.endswith(".png"))
    assert "Se para al publicar el tercer anuncio" in todo
    assert "clave-super-secreta-123" not in todo and "abcdefghijklmnop" not in todo
    assert "xyz123456" not in todo
    assert "Cuentas:" in todo and "Cuenta 1 (DEMO)" in todo


def test_por_defecto_va_al_escritorio(monkeypatch, tmp_path):
    from pathlib import Path

    from lot_bot.core import support_report

    (tmp_path / "Desktop").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert support_report.default_folder() == tmp_path / "Desktop"


def test_el_informe_lleva_el_numero_de_licencia_pero_no_la_clave(app_with_data, tmp_path, temp_paths):
    import random

    from lot_bot.licensing.config import LicenseConfig
    from lot_bot.licensing.manager import LicenseManager
    from tests.test_licencias import DEVICE, KEY, T0, FakeServer, Signer

    clock = [T0]
    signer = Signer()
    manager = LicenseManager(
        temp_paths.config,
        config=LicenseConfig("https://licencias.test", (signer.public_raw,)),
        client=FakeServer(signer, clock), device=DEVICE, clock=lambda: clock[0], rng=random.Random(1),
    )
    assert manager.activate(KEY).ok
    app_with_data.license = manager
    zip_path = build_report(app_with_data, "prueba", tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        sistema = zf.read("sistema.txt").decode("utf-8")
    assert "Licencia: activa · n.º 7" in sistema
    assert "LOTB-••••-••••-EF56" in sistema
    assert KEY not in sistema


def test_informe_cuando_no_arranca(temp_paths, tmp_path):
    from lot_bot.core.support_report import build_crash_report

    register_secret("clave-de-arranque-secreta-9")
    temp_paths.logs.mkdir(parents=True, exist_ok=True)
    (temp_paths.logs / "lot_bot.log").write_text("ERROR al arrancar con clave-de-arranque-secreta-9\n", encoding="utf-8")
    (temp_paths.logs / "datos.db").write_bytes(b"no debe ir")
    path = build_crash_report("Traceback: fallo con clave-de-arranque-secreta-9", tmp_path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        text = "".join(zf.read(n).decode("utf-8", "replace") for n in names)
    assert {"LEEME.txt", "sistema.txt", "error.txt", "logs/lot_bot.log"} <= names
    assert not any(n.endswith(".db") for n in names)
    assert "clave-de-arranque-secreta-9" not in text and "Traceback" in text
