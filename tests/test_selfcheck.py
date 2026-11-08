"""La autoprueba existe y se puede lanzar con --autoprueba."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_autoprueba_sin_navegador_comprueba_lo_basico(monkeypatch, tmp_path):
    from lot_bot import selfcheck

    monkeypatch.setattr(selfcheck, "_check_browser", lambda workdir: "omitido en la prueba")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert selfcheck.run() == 0


def test_el_arranque_acepta_autoprueba():
    source = (ROOT / "run_lot_bot.py").read_text(encoding="utf-8")
    assert "--autoprueba" in source
