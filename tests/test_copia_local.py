"""Copia de seguridad diaria de los datos del cliente (SQLite local)."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from lot_bot.core.local_backup import daily_backup


def _db(path, rows=3):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS anuncios (id INTEGER PRIMARY KEY, titulo TEXT)")
    con.executemany("INSERT INTO anuncios (titulo) VALUES (?)", [(f"Sofá {i}",) for i in range(rows)])
    con.commit()
    return con


def test_copia_del_dia_restaurable_y_una_sola_vez(tmp_path):
    db = tmp_path / "lot_bot.db"
    open_con = _db(db)  # la base sigue abierta (como con LOT Bot en marcha)
    copy = daily_backup(db, today=date(2026, 11, 13))
    assert copy is not None and copy.name == "lot_bot-20261113.db"
    restored = sqlite3.connect(copy)
    assert restored.execute("SELECT count(*) FROM anuncios").fetchone()[0] == 3
    restored.close()
    assert daily_backup(db, today=date(2026, 11, 13)) is None  # hoy ya hay copia
    open_con.close()


def test_se_guardan_solo_las_7_mas_recientes(tmp_path):
    db = tmp_path / "lot_bot.db"
    _db(db).close()
    start = date(2026, 1, 1)
    for day in range(10):
        daily_backup(db, today=start + timedelta(days=day))
    copies = sorted((tmp_path / "copias").glob("lot_bot-*.db"))
    assert len(copies) == 7
    assert copies[0].name == "lot_bot-20260104.db"


def test_sin_base_o_con_base_danada_no_rompe_nada(tmp_path):
    assert daily_backup(tmp_path / "no-existe.db") is None
    broken = tmp_path / "lot_bot.db"
    broken.write_bytes(b"esto no es una base de datos" * 100)
    assert daily_backup(broken, today=date(2026, 2, 2)) is None
    assert not list((tmp_path / "copias").glob("*.parte"))
