"""Huella anónima del ordenador (para vincular la licencia a él).

Se parte del identificador que el propio sistema da a la instalación:

* Windows: ``MachineGuid`` del registro (HKLM\\SOFTWARE\\Microsoft\\Cryptography).
* macOS: ``IOPlatformUUID`` (``ioreg``).
* Linux: ``/etc/machine-id``.

Nunca se envía ese identificador: solo un SHA-256 con un prefijo propio, así
que no sirve para nada fuera de LOT Bot. Si el sistema no da ninguno, se crea
uno al azar y se guarda en la carpeta de datos.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SALT = "lotbot-device-v1|"
_FALLBACK_FILE = "device_id"


def _windows_machine_guid() -> str | None:
    try:
        import winreg  # type: ignore[import-not-found]

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip() or None
    except Exception as exc:  # pragma: no cover - solo Windows
        logger.debug("No se pudo leer MachineGuid: %s", type(exc).__name__)
        return None


def _mac_platform_uuid() -> str | None:
    try:
        output = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except Exception as exc:  # pragma: no cover - solo macOS
        logger.debug("No se pudo leer IOPlatformUUID: %s", type(exc).__name__)
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output or "")
    return match.group(1).strip() if match else None


def _linux_machine_id() -> str | None:
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(candidate).read_text(encoding="ascii").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def system_machine_id() -> str | None:
    if sys.platform.startswith("win"):
        return _windows_machine_guid()
    if sys.platform == "darwin":
        return _mac_platform_uuid()
    return _linux_machine_id()


def _fallback_id(folder: Path) -> str:
    path = folder / _FALLBACK_FILE
    try:
        value = path.read_text(encoding="ascii").strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(16)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="ascii")
    except OSError:  # pragma: no cover - disco de solo lectura
        logger.warning("No se ha podido guardar el identificador del ordenador.")
    return value


@dataclass(frozen=True)
class DeviceInfo:
    fingerprint: str
    name: str
    os: str


def device_info(data_folder: Path, *, machine_id: str | None = None) -> DeviceInfo:
    """Huella (64 caracteres hex), nombre del equipo y sistema operativo."""
    raw = machine_id if machine_id is not None else system_machine_id()
    source = raw or _fallback_id(data_folder)
    fingerprint = hashlib.sha256((_SALT + source.strip().lower()).encode("utf-8")).hexdigest()
    system = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, platform.system() or "Linux")
    release = platform.mac_ver()[0] if sys.platform == "darwin" else platform.release()
    name = (platform.node() or "Ordenador").strip()[:80]
    return DeviceInfo(fingerprint=fingerprint, name=name, os=f"{system} {release}".strip()[:60])
