"""¿La instalación es la oficial?

Al arrancar el programa instalado (Windows .exe / Mac .app), LOT Bot pide al
servidor la lista FIRMADA de huellas (SHA-256) de los ficheros oficiales de su
versión y las compara con las de sus propios ficheros. El resultado se cuenta
al servidor y sale en /admin → Alertas si no coincide.

Solo informa: nunca bloquea ni borra nada (un disco dañado o un antivirus
también pueden cambiar un fichero). Si no hay conexión o la versión no tiene
lista, no pasa nada.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from lot_bot import __version__
from lot_bot.licensing.lease import LeaseError, verify_signed

logger = logging.getLogger(__name__)

TOKEN_TYPE = "lotbot-integrity"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class IntegrityResult:
    #: «correcta», «modificada», «sin_datos» (versión sin lista) o «sin_conexion».
    state: str
    detail: str = ""


def installation_root(platform: str, executable: str | None = None) -> Path | None:
    """Carpeta desde la que se cuentan las rutas de la lista."""
    exe = Path(executable or sys.executable).resolve()
    if platform == "windows-x64":
        return exe.parent
    if exe.parent.name == "MacOS" and exe.parents[2].suffix == ".app":
        return exe.parents[2]
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(root: Path, files: dict[str, str]) -> list[str]:
    """Ficheros que faltan o no coinciden (rutas de la lista, siempre dentro de `root`)."""
    wrong: list[str] = []
    for name, expected in sorted(files.items()):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            wrong.append(name)
            continue
        path = root.joinpath(*relative.parts)
        if not path.is_file() or _sha256(path) != expected:
            wrong.append(name)
    return wrong


def check_installation(
    manager: Any,
    platform: str,
    root: Path,
    *,
    version: str = __version__,
    transport: httpx.BaseTransport | None = None,
    clock=time.time,
) -> IntegrityResult:
    key = manager.stored_key()
    if not key:
        return IntegrityResult("sin_datos", "sin licencia")
    device = manager.device
    server = manager.config.server
    body = {"key": key, "device": {"fingerprint": device.fingerprint, "app_version": version}, "platform": platform}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            data = client.post(f"{server}/api/v1/integrity", json=body).json()
    except (httpx.HTTPError, ValueError):
        return IntegrityResult("sin_conexion")
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        return IntegrityResult("sin_datos", "esta versión no tiene lista de huellas")
    try:
        payload = verify_signed(token, manager.config.public_keys, TOKEN_TYPE)
    except LeaseError as exc:
        logger.warning("Lista de huellas no válida: %s", exc)
        return IntegrityResult("sin_datos", "lista no válida")
    if (
        payload.get("ver") != version
        or payload.get("plat") != platform
        or payload.get("dev") != device.fingerprint
        or int(payload.get("exp", 0)) < clock()
    ):
        return IntegrityResult("sin_datos", "lista de otra versión u ordenador")
    files = payload.get("files") or {}
    if not isinstance(files, dict) or not files:
        return IntegrityResult("sin_datos", "lista vacía")
    wrong = compare(root, {str(k): str(v) for k, v in files.items()})
    result = IntegrityResult("modificada", ", ".join(wrong)[:300]) if wrong else IntegrityResult("correcta")
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            client.post(
                f"{server}/api/v1/integrity/report",
                json={**body, "result": result.state, "detail": result.detail},
            )
    except httpx.HTTPError:
        pass
    if wrong:
        logger.warning("La instalación no coincide con la oficial: %s", result.detail)
    else:
        logger.info("Instalación comprobada: coincide con la oficial.")
    return result
