"""«Enviar informe a soporte»: un .zip con lo necesario para ver qué ha fallado.

Qué lleva:
  - LEEME.txt: lo que ha pasado (lo escribe el cliente) y qué incluye el zip;
  - sistema.txt: versión de LOT Bot, sistema, modo, cuentas (nombre y estado)
    y cómo va la cola de publicación;
  - historial.txt: lo último que ha hecho LOT Bot;
  - logs/: los registros técnicos;
  - navegador/: capturas y contexto de los últimos fallos al publicar.

Qué NO lleva nunca: contraseñas, cookies, sesiones de navegador, claves de
API, la base de datos ni la clave maestra. Todo el texto pasa además por el
mismo filtro que borra secretos de los registros.
"""

from __future__ import annotations

import logging
import platform
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from lot_bot.logs.redaction import redact

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

#: Capturas de fallos de los últimos días que se incluyen (las más nuevas).
SHOT_DAYS = 7
MAX_SHOTS = 40
MAX_LOG_BYTES = 8_000_000
#: Nunca entran en el informe, aunque estén en la carpeta de registros.
NEVER = {".db", ".sqlite", ".sqlite3", ".key", ".pem", ".env"}


def default_folder() -> Path:
    """El Escritorio (o Descargas) del usuario: donde lo encuentra fácil."""
    home = Path.home()
    for name in ("Desktop", "Escritorio", "Downloads", "Descargas"):
        if (home / name).is_dir():
            return home / name
    return home


def _safe_text(path: Path) -> str:
    return redact(path.read_text(encoding="utf-8", errors="replace"))


def _system_info(app: Application) -> str:
    from lot_bot import __version__

    lines = [
        f"Fecha del informe: {datetime.now():%d/%m/%Y %H:%M:%S}",
        f"LOT Bot: {__version__}",
    ]
    updater = getattr(app, "updater", None)
    if updater is not None:
        try:
            lines.append(f"Versión instalada: {updater.current_version()}")
        except Exception:
            pass
    manager = getattr(app, "license", None)
    if manager is not None:
        try:
            status = manager.status()
            lines.append(
                f"Licencia: {status.state.value}"
                + (f" · n.º {status.license_id}" if status.license_id else "")
                + (f" · {status.key_masked}" if status.key_masked else "")
                + (f" · {status.code}" if status.code else "")
                + (f" · ordenador {manager.device.fingerprint[:12]}" if status.enforced else "")
            )
        except Exception:
            pass
    lines += [
        f"Sistema: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {sys.version.split()[0]}",
        f"Modo: {getattr(app, 'backend_label', '?')}",
        "",
        "Cuentas:",
    ]
    try:
        for a in app.accounts.list_accounts():
            lines.append(f"  · {a.alias} — {a.status.value}{' (DEMO)' if a.is_demo else ''}")
    except Exception as exc:
        lines.append(f"  (no se han podido leer: {exc})")
    try:
        progress = app.publish_queue.progress(None)
        settings = app.publish_queue.settings()
        lines += ["", "Ajustes de publicación:"]
        lines += [f"  · {k}: {v}" for k, v in sorted(settings.items()) if not k.startswith("_")]
        if progress is not None:
            lines += [
                "",
                f"Última cola: {progress.name} — {progress.status}",
                f"  publicados {progress.published} · pendientes {progress.pending} · "
                f"fallidos {progress.failed} · total {progress.total}",
            ]
            if progress.pause_reason:
                lines.append(f"  en pausa: {progress.pause_reason}")
            for t in progress.tasks:
                if t["error"]:
                    lines.append(f"  · #{t['posicion']} {t['cuenta']}: {t['estado']} — {t['error']}")
    except Exception as exc:
        lines.append(f"(cola: {exc})")
    return redact("\n".join(lines))


def _history(app: Application, limit: int = 300) -> str:
    rows = []
    try:
        for e in app.audit.recent(limit=limit):
            parts = [f"{e.timestamp:%d/%m %H:%M:%S}", e.result, e.action]
            for extra in (e.account_ref, e.target, e.detail, e.error):
                if extra:
                    parts.append(str(extra))
            rows.append(" | ".join(parts))
    except Exception as exc:
        rows.append(f"(no se ha podido leer el historial: {exc})")
    return redact("\n".join(rows))


def build_report(app: Application, description: str = "", folder: Path | None = None) -> Path:
    """Crea el .zip del informe y devuelve dónde está."""
    folder = Path(folder) if folder else default_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"LOT-Bot-informe-{datetime.now():%Y%m%d-%H%M%S}.zip"
    logs_dir = Path(app.paths.logs)
    included: list[str] = []

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sistema.txt", _system_info(app))
        zf.writestr("historial.txt", _history(app))

        total = 0
        for log in sorted(logs_dir.glob("*.log*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if log.suffix in NEVER or total > MAX_LOG_BYTES:
                continue
            text = _safe_text(log)
            total += len(text)
            zf.writestr(f"logs/{log.name}", text)
            included.append(f"logs/{log.name}")

        shots_dir = logs_dir / "navegador"
        if shots_dir.is_dir():
            since = datetime.now() - timedelta(days=SHOT_DAYS)
            recent = [
                p for p in shots_dir.iterdir()
                if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".json", ".txt", ".html")
                and datetime.fromtimestamp(p.stat().st_mtime) >= since
            ]
            recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            images = 0
            for p in recent:
                if p.suffix.lower() in (".png", ".jpg"):
                    if images >= MAX_SHOTS:
                        continue
                    images += 1
                    zf.write(p, f"navegador/{p.name}")
                else:
                    zf.writestr(f"navegador/{p.name}", _safe_text(p))
                included.append(f"navegador/{p.name}")

        readme = [
            "INFORME DE LOT BOT PARA SOPORTE",
            "",
            "Qué ha pasado (según el cliente):",
            redact(description.strip()) or "(sin descripción)",
            "",
            f"Creado: {datetime.now():%d/%m/%Y %H:%M}",
            "",
            "Incluye: sistema.txt (versión, cuentas, cola), historial.txt (lo último que ha",
            "hecho LOT Bot), los registros técnicos y las capturas de los últimos fallos.",
            "NO incluye contraseñas, cookies, sesiones de navegador, claves de API ni la base",
            "de datos.",
        ]
        zf.writestr("LEEME.txt", "\n".join(readme))

    logger.info("Informe para soporte creado: %s (%d archivos)", target, len(included) + 3)
    try:
        app.audit.record_success("Informe para soporte creado", detail=target.name)
    except Exception:
        pass
    return target


def build_crash_report(error_text: str, folder: Path | None = None) -> Path:
    """Informe cuando LOT Bot NO ha podido arrancar (sin aplicación cargada):
    el error, el sistema y los registros, con el mismo filtro de secretos."""
    from lot_bot import __version__
    from lot_bot.config.paths import get_paths

    folder = Path(folder) if folder else default_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"LOT-Bot-informe-arranque-{datetime.now():%Y%m%d-%H%M%S}.zip"
    try:
        logs_dir = Path(get_paths().logs)
    except Exception:  # sin carpeta de datos: solo el error
        logs_dir = None
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "LEEME.txt",
            "INFORME DE LOT BOT PARA SOPORTE (no ha podido arrancar)\n\n"
            f"Creado: {datetime.now():%d/%m/%Y %H:%M}\n"
            "Incluye: el error, el sistema y los registros técnicos.\n"
            "NO incluye contraseñas, cookies, sesiones de navegador, claves ni la base de datos.\n",
        )
        zf.writestr(
            "sistema.txt",
            f"LOT Bot: {__version__}\nSistema: {platform.system()} {platform.release()} "
            f"({platform.machine()})\nPython: {sys.version.split()[0]}\n",
        )
        zf.writestr("error.txt", redact(error_text))
        if logs_dir is not None and logs_dir.is_dir():
            total = 0
            for log in sorted(logs_dir.glob("*.log*"), key=lambda p: p.stat().st_mtime, reverse=True):
                if log.suffix in NEVER or total > MAX_LOG_BYTES:
                    continue
                text = _safe_text(log)
                total += len(text)
                zf.writestr(f"logs/{log.name}", text)
    logger.info("Informe de arranque para soporte creado: %s", target)
    return target
