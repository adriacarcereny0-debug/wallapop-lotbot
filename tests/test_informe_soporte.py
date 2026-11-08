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
