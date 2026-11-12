"""Actualizaciones del programa INSTALADO (Windows .exe / Mac .app).

Sustituye al actualizador por git en las copias instaladas (el de git sigue
para quien usa el código fuente). Mismos métodos que `Updater`, así la franja
«Hay una actualización» y Configuración → Acerca de funcionan igual.

1. `check`: pregunta al servidor con la licencia. Si hay versión nueva, la
   respuesta trae un pase FIRMADO (Ed25519, misma clave que las licencias) con
   la versión, la plataforma, este ordenador, el tamaño y la huella SHA-256
   del instalador. Sin firma válida no se ofrece nada.
2. `apply`: descarga el instalador, comprueba tamaño y SHA-256 contra el pase
   y lo instala:
   - Windows: el instalador (Inno Setup) en modo silencioso, sin permisos de
     administrador; cierra LOT Bot, lo sustituye y lo vuelve a abrir.
   - Mac: un pequeño guion espera a que LOT Bot se cierre, monta el .dmg,
     comprueba la firma de la app, sustituye «LOT Bot.app» y la abre.
   Si algo no cuadra, no se instala nada y la versión actual sigue igual.

Los datos del cliente viven fuera del programa: actualizar no los toca.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform as platform_module
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from lot_bot import __version__
from lot_bot.core.updater import UpdateInfo, UpdateResult
from lot_bot.licensing.lease import LeaseError, verify_signed

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
UPDATE_TYPE = "lotbot-update"
CHUNK = 1024 * 256


def current_platform() -> str | None:
    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform == "darwin":
        return "mac-arm64" if platform_module.machine() == "arm64" else "mac-intel"
    return None


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return (0,)


def mac_app_bundle(executable: str | None = None) -> Path | None:
    """«/Applications/LOT Bot.app» a partir de …/LOT Bot.app/Contents/MacOS/LOT-Bot."""
    exe = Path(executable or sys.executable).resolve()
    if exe.parent.name == "MacOS" and exe.parents[2].suffix == ".app":
        return exe.parents[2]
    return None


MAC_INSTALL_SCRIPT = r"""#!/bin/bash
# Instala la versión nueva de LOT Bot cuando la actual se ha cerrado.
PID="$1"; DMG="$2"; APP="$3"; LOG="$4"
exec >>"$LOG" 2>&1
echo "== $(date) actualizando $APP"
for i in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
MNT="$(mktemp -d)"
fail() { echo "ERROR: $1"; hdiutil detach "$MNT" -quiet 2>/dev/null; rm -rf "$APP.nuevo"; open "$APP"; exit 1; }
hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MNT" -quiet || fail "no se ha podido abrir el .dmg"
NEW="$MNT/LOT Bot.app"
[ -d "$NEW" ] || fail "el .dmg no trae LOT Bot.app"
codesign --verify --deep --strict "$NEW" || fail "la firma de la app nueva no es válida"
rm -rf "$APP.nuevo"
ditto "$NEW" "$APP.nuevo" || fail "no se ha podido copiar la app nueva"
hdiutil detach "$MNT" -quiet
rm -rf "$APP.anterior"
mv "$APP" "$APP.anterior" || fail "no se ha podido apartar la app actual"
if ! mv "$APP.nuevo" "$APP"; then mv "$APP.anterior" "$APP"; fail "no se ha podido poner la app nueva"; fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
rm -rf "$APP.anterior" "$DMG"
echo "OK"
open "$APP"
"""


@dataclass
class Offer:
    version: str
    notes: str
    mandatory: bool
    size: int
    sha256: str
    download: str


class ReleaseUpdater:
    #: El instalador vuelve a abrir LOT Bot: la interfaz solo tiene que cerrarse.
    restarts_itself = True

    def __init__(
        self,
        license_manager: Any,
        downloads_dir: Path,
        *,
        version: str = __version__,
        platform: str | None = None,
        channel: str = "estable",
        transport: httpx.BaseTransport | None = None,
        launcher: Callable[[list[str]], Any] | None = None,
        clock: Callable[[], float] = time.time,
        app_bundle: Path | None = None,
    ) -> None:
        self.license = license_manager
        self.downloads_dir = Path(downloads_dir)
        self.version = version
        self.platform = platform if platform is not None else current_platform()
        self.channel = channel
        self._transport = transport
        self._launch = launcher or _launch_detached
        self._clock = clock
        self._app_bundle = app_bundle
        self._offer: Offer | None = None

    # ------------------------------------------------------------------
    # Lo mismo que el actualizador por git
    # ------------------------------------------------------------------
    @property
    def supported(self) -> bool:
        return bool(self.platform) and self.license is not None and bool(self.license.stored_key())

    def unsupported_reason(self) -> str:
        if not self.platform:
            return "Las actualizaciones automáticas son para Windows y Mac."
        return "Activa tu licencia (Configuración → Licencia) para recibir las actualizaciones."

    def current_version(self) -> str:
        return self.version

    def previous_version(self) -> str | None:
        return None

    def rollback(self) -> UpdateResult:
        return UpdateResult(
            False,
            "En la versión instalada no se vuelve atrás desde aquí: si una versión da problemas, "
            "la retiramos y LOT Bot recibe la siguiente buena. Escríbenos si lo necesitas.",
        )

    # ------------------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=True)

    def check(self) -> UpdateInfo:
        if not self.supported:
            return UpdateInfo(False, message=self.unsupported_reason())
        key = self.license.stored_key()
        device = self.license.device
        body = {
            "key": key,
            "device": {"fingerprint": device.fingerprint, "app_version": self.version},
            "platform": self.platform,
            "channel": self.channel,
        }
        url = f"{self.license.config.server}/api/v1/updates/check"
        try:
            with self._client() as client:
                response = client.post(url, json=body, headers={"User-Agent": f"LOT-Bot/{self.version}"})
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("No se ha podido buscar actualizaciones: %s", type(exc).__name__)
            return UpdateInfo(False, message="No se ha podido consultar si hay versión nueva (¿hay Internet?).")
        if not isinstance(data, dict) or data.get("ok") is not True:
            message = (data or {}).get("message") if isinstance(data, dict) else ""
            return UpdateInfo(False, message=message or "No se ha podido consultar si hay versión nueva.")
        update = data.get("update")
        if not update:
            self._offer = None
            return UpdateInfo(False, latest=self.version, message="LOT Bot está al día.")
        try:
            offer = self._verify(update, device.fingerprint)
        except LeaseError as exc:
            logger.error("Actualización rechazada: %s", exc)
            return UpdateInfo(False, message="La actualización recibida no es válida: no se instala.")
        self._offer = offer
        notes = [line.strip("•- ").strip() for line in offer.notes.splitlines() if line.strip()]
        return UpdateInfo(
            True,
            behind=0,
            changes=notes or ["Mejoras y arreglos."],
            latest=offer.version,
            message=f"Hay una versión nueva: {offer.version}.",
            mandatory=offer.mandatory,
        )

    def _verify(self, update: dict[str, Any], fingerprint: str) -> Offer:
        payload = verify_signed(str(update.get("token", "")), self.license.config.public_keys, UPDATE_TYPE)
        version = str(payload.get("ver", ""))
        if payload.get("plat") != self.platform:
            raise LeaseError("es para otro sistema")
        if payload.get("dev") != fingerprint:
            raise LeaseError("es para otro ordenador")
        if int(payload.get("exp", 0)) < self._clock():
            raise LeaseError("ha caducado")
        if version_tuple(version) <= version_tuple(self.version):
            raise LeaseError("no es más nueva que la instalada")
        sha256 = str(payload.get("sha256", ""))
        size = int(payload.get("size", 0))
        if len(sha256) != 64 or size <= 0:
            raise LeaseError("le faltan datos")
        if update.get("version") != version or update.get("sha256") != sha256:
            raise LeaseError("los datos no cuadran con la firma")
        return Offer(
            version=version,
            notes=str(update.get("notes") or ""),
            mandatory=bool(payload.get("mandatory")),
            size=size,
            sha256=sha256,
            download=str(update.get("download") or ""),
        )

    # ------------------------------------------------------------------
    def download(self, offer: Offer) -> Path:
        """Descarga y comprueba (tamaño y SHA-256). Lanza LeaseError si no cuadra."""
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        ext = ".exe" if self.platform == "windows-x64" else ".dmg"
        target = self.downloads_dir / f"LOT-Bot-{offer.version}-{self.platform}{ext}"
        partial = target.with_suffix(target.suffix + ".parte")
        digest = hashlib.sha256()
        received = 0
        try:
            with self._client() as client, client.stream("GET", offer.download) as response:
                if response.status_code != 200:
                    raise LeaseError(f"la descarga ha fallado ({response.status_code})")
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(CHUNK):
                        received += len(chunk)
                        if received > offer.size:
                            raise LeaseError("el fichero descargado es más grande de lo esperado")
                        digest.update(chunk)
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            raise LeaseError(f"la descarga se ha cortado ({type(exc).__name__})") from exc
        except LeaseError:
            partial.unlink(missing_ok=True)
            raise
        if received != offer.size or digest.hexdigest() != offer.sha256:
            partial.unlink(missing_ok=True)
            raise LeaseError("el fichero descargado no coincide con la huella firmada")
        os.replace(partial, target)
        for old in self.downloads_dir.glob("LOT-Bot-*"):
            if old != target:
                old.unlink(missing_ok=True)
        return target

    def apply(self) -> UpdateResult:
        if not self.supported:
            return UpdateResult(False, self.unsupported_reason())
        offer = self._offer
        if offer is None:
            info = self.check()
            offer = self._offer
            if offer is None:
                return UpdateResult(False, info.message)
        try:
            installer = self.download(offer)
        except LeaseError as exc:
            logger.error("Actualización %s: %s", offer.version, exc)
            return UpdateResult(False, f"No se ha instalado la versión {offer.version}: {exc}.")
        try:
            self._start_install(installer)
        except Exception as exc:  # noqa: BLE001 - se informa del fallo
            logger.exception("No se ha podido abrir el instalador")
            return UpdateResult(False, f"No se ha podido abrir el instalador: {exc}")
        logger.info("Instalando LOT Bot %s (antes %s).", offer.version, self.version)
        return UpdateResult(
            True,
            f"Se está instalando LOT Bot {offer.version}. LOT Bot se cerrará y se abrirá solo en "
            "unos segundos.",
            previous=self.version,
            current=offer.version,
        )

    def _start_install(self, installer: Path) -> None:
        if self.platform == "windows-x64":
            self._launch(
                [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/SP-"]
            )
            return
        bundle = self._app_bundle or mac_app_bundle()
        if bundle is None:
            raise RuntimeError("no se encuentra «LOT Bot.app»")
        script = self.downloads_dir / "instalar.sh"
        script.write_text(MAC_INSTALL_SCRIPT, encoding="utf-8")
        script.chmod(0o700)
        log = self.downloads_dir / "instalar.log"
        self._launch(["/bin/bash", str(script), str(os.getpid()), str(installer), str(bundle), str(log)])


def _launch_detached(command: list[str]) -> None:
    kwargs: dict[str, Any] = {"close_fds": True}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    logger.info("Lanzando: %s", " ".join(shlex.quote(part) for part in command))
    subprocess.Popen(command, **kwargs)
