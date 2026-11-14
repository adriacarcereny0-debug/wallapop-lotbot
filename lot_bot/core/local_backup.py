"""Copia de seguridad diaria de los datos del cliente (base de datos local).

Al abrir LOT Bot, si hoy aún no hay copia, se guarda una de `lot_bot.db` en
`<carpeta de datos>/copias/lot_bot-AAAAMMDD.db` con la API de copia de SQLite
(segura aunque la base esté abierta). Se guardan las 7 más recientes.

Restaurar: cerrar LOT Bot y copiar la copia elegida encima de `lot_bot.db`.
Nunca bloquea el arranque: si algo falla, solo se apunta en el registro.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

KEEP = 7
FOLDER = "copias"


def daily_backup(database: Path, *, today: date | None = None, keep: int = KEEP) -> Path | None:
    """Hace la copia de hoy si falta. Devuelve su ruta (o None si no hacía falta o falló)."""
    database = Path(database)
    if not database.is_file() or database.stat().st_size == 0:
        return None
    folder = database.parent / FOLDER
    target = folder / f"lot_bot-{(today or date.today()):%Y%m%d}.db"
    if target.exists():
        return None
    partial = target.with_suffix(".parte")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            copy = sqlite3.connect(partial)
            try:
                source.backup(copy)
                ok = copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                copy.close()
        finally:
            source.close()
        if not ok:
            partial.unlink(missing_ok=True)
            logger.warning("La copia de seguridad local no ha pasado la comprobación: no se guarda.")
            return None
        partial.replace(target)
    except (OSError, sqlite3.Error) as exc:
        partial.unlink(missing_ok=True)
        logger.warning("No se ha podido hacer la copia de seguridad local: %s", exc)
        return None
    for old in sorted(folder.glob("lot_bot-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    logger.info("Copia de seguridad de los datos: %s", target.name)
    return target
