"""Actualizaciones del programa instalado: pase firmado, descarga comprobada
(tamaño + SHA-256) e instalación en Windows (instalador silencioso) y Mac
(guion que sustituye «LOT Bot.app»). El servidor se simula con httpx."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from pathlib import Path

import httpx
import pytest

from lot_bot.core.release_updater import (
    MAC_INSTALL_SCRIPT,
    ReleaseUpdater,
    current_platform,
    mac_app_bundle,
    version_tuple,
)
from lot_bot.licensing.config import LicenseConfig
from lot_bot.licensing.fingerprint import DeviceInfo
from lot_bot.licensing.manager import LicenseManager
from tests.test_licencias import KEY, T0, FakeServer, Signer

DEVICE = DeviceInfo(fingerprint="a" * 64, name="PC", os="Windows 11")
INSTALLER = b"MZ instalador de LOT Bot 1.1.0 " * 1000


class Server:
    """Servidor de actualizaciones simulado."""

    def __init__(self, signer: Signer, clock: list[float]) -> None:
        self.signer = signer
        self.clock = clock
        self.version = "1.1.0"
        self.platform = "windows-x64"
        self.payload = INSTALLER
        self.served = INSTALLER
        self.device = DEVICE.fingerprint
        self.mandatory = False
        self.token_override: str | None = None
        self.no_update = False
        self.status = 200
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if request.url.path == "/api/v1/updates/check":
            body = json.loads(request.content)
            assert body["key"] == KEY and body["platform"]
            if self.status != 200:
                return httpx.Response(self.status, json={"ok": False, "code": "LICENSE_REVOKED", "message": "Esta licencia ha sido revocada."})
            if self.no_update:
                return httpx.Response(200, json={"ok": True, "update": None})
            sha = hashlib.sha256(self.payload).hexdigest()
            token = self.token_override or self.signer.token(
                ver=self.version, plat=self.platform, sha256=sha, size=len(self.payload),
                mandatory=self.mandatory, dev=self.device, iat=int(self.clock[0]), exp=int(self.clock[0]) + 86400,
            )
            return httpx.Response(200, json={"ok": True, "update": {
                "version": self.version, "notes": "• Más rápido\n• Arreglos", "mandatory": self.mandatory,
                "size": len(self.payload), "sha256": sha, "token": token,
                "download": "https://licencias.test/api/v1/updates/download?t=x",
            }})
        if request.url.path == "/api/v1/updates/download":
            return httpx.Response(302, headers={"Location": "https://descargas.test/instalador"})
        if request.url.host == "descargas.test":
            return httpx.Response(200, content=self.served)
        return httpx.Response(404)


def _token_type(signer: Signer):
    """El Signer de las pruebas firma «lotbot-lease»; aquí hace falta «lotbot-update»."""
    original = signer.token

    def token(**fields):
        import base64

        payload = {"v": 1, "typ": "lotbot-update", "kid": signer.kid, **fields}
        body = "LBT1." + base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return body + "." + base64.urlsafe_b64encode(signer.private.sign(body.encode())).rstrip(b"=").decode()

    signer.token = token
    return original


@pytest.fixture()
def env(temp_paths):
    clock = [T0]
    signer = Signer()
    licenses = FakeServer(signer, clock)
    manager = LicenseManager(
        temp_paths.config,
        config=LicenseConfig(server="https://licencias.test", public_keys=(signer.public_raw,)),
        client=licenses, device=DEVICE, clock=lambda: clock[0], rng=random.Random(1),
    )
    assert manager.activate(KEY).ok
    _token_type(signer)
    server = Server(signer, clock)
    launched: list[list[str]] = []
    updater = ReleaseUpdater(
        manager, temp_paths.root / "actualizaciones", version="1.0.0", platform="windows-x64",
        transport=httpx.MockTransport(server.handler), launcher=launched.append, clock=lambda: clock[0],
    )
    return updater, server, launched, temp_paths


def test_hay_version_nueva_se_descarga_comprueba_e_instala_en_windows(env):
    updater, server, launched, paths = env
    info = updater.check()
    assert info.available and info.latest == "1.1.0"
    assert info.changes == ["Más rápido", "Arreglos"]
    result = updater.apply()
    assert result.ok, result.message
    installer = Path(launched[0][0])
    assert installer.read_bytes() == INSTALLER
    assert launched[0][1:] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/SP-"]
    assert updater.restarts_itself


def test_al_dia(env):
    updater, server, launched, _ = env
    server.no_update = True
    info = updater.check()
    assert not info.available and "al día" in info.message
    assert not updater.apply().ok and launched == []


@pytest.mark.parametrize(
    ("cambio", "texto"),
    [
        ("otra_firma", "no es válida"),
        ("otra_plataforma", "no es válida"),
        ("otro_ordenador", "no es válida"),
        ("mas_vieja", "no es válida"),
    ],
)
def test_pases_que_no_cuadran_no_se_instalan(env, cambio, texto):
    updater, server, launched, _ = env
    if cambio == "otra_firma":
        impostor = Signer()
        _token_type(impostor)
        server.token_override = impostor.token(ver="1.1.0", plat="windows-x64", sha256="0" * 64, size=10,
                                               mandatory=False, dev=DEVICE.fingerprint, iat=int(T0), exp=int(T0) + 999)
    elif cambio == "otra_plataforma":
        server.platform = "mac-arm64"
    elif cambio == "otro_ordenador":
        server.device = "b" * 64
    elif cambio == "mas_vieja":
        server.version = "0.9.0"
    info = updater.check()
    assert not info.available and texto in info.message
    assert not updater.apply().ok and launched == []


def test_instalador_cambiado_por_el_camino_no_se_instala(env):
    updater, server, launched, paths = env
    server.served = INSTALLER[:-1] + b"X"  # mismo tamaño, otro contenido
    assert updater.check().available
    result = updater.apply()
    assert not result.ok and "huella" in result.message
    assert launched == []
    assert not list((paths.root / "actualizaciones").glob("LOT-Bot-*"))


def test_instalador_mas_grande_se_corta_y_se_borra(env):
    updater, server, launched, paths = env
    server.served = INSTALLER + b"extra"
    assert updater.check().available
    result = updater.apply()
    assert not result.ok and "más grande" in result.message
    assert not list((paths.root / "actualizaciones").glob("*.parte"))


def test_sin_licencia_activa_el_servidor_no_da_nada(env):
    updater, server, launched, _ = env
    server.status = 403
    info = updater.check()
    assert not info.available and "revocada" in info.message


def test_sin_licencia_guardada_no_se_busca(temp_paths):
    manager = LicenseManager(temp_paths.config, config=LicenseConfig("https://x", (b"x" * 32,)), device=DEVICE)
    updater = ReleaseUpdater(manager, temp_paths.root / "a", platform="windows-x64")
    assert not updater.supported
    assert "licencia" in updater.unsupported_reason().lower()
    assert not updater.check().available


def test_sin_conexion(env):
    updater, server, launched, _ = env

    def caida(request):
        raise httpx.ConnectError("sin red")

    updater._transport = httpx.MockTransport(caida)
    info = updater.check()
    assert not info.available and "Internet" in info.message


def test_version_obligatoria(env):
    updater, server, launched, _ = env
    server.mandatory = True
    assert updater.check().mandatory


def test_mac_lanza_el_guion_que_sustituye_la_app(env, tmp_path):
    updater, server, launched, paths = env
    server.platform = "mac-arm64"
    updater.platform = "mac-arm64"
    bundle = tmp_path / "Applications" / "LOT Bot.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    updater._app_bundle = bundle
    assert updater.check().available
    result = updater.apply()
    assert result.ok, result.message
    command = launched[0]
    assert command[0] == "/bin/bash" and command[4] == str(bundle)
    assert command[3].endswith(".dmg") and Path(command[3]).read_bytes() == INSTALLER
    script = Path(command[1]).read_text()
    assert "codesign --verify" in script and "hdiutil attach" in script


def test_el_guion_de_mac_es_bash_valido():
    checked = subprocess.run(["bash", "-n"], input=MAC_INSTALL_SCRIPT, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr


def test_utilidades():
    assert version_tuple("1.10.0") > version_tuple("1.9.9")
    assert current_platform() in (None, "windows-x64", "mac-arm64", "mac-intel")
    assert mac_app_bundle("/Applications/LOT Bot.app/Contents/MacOS/LOT-Bot") == Path("/Applications/LOT Bot.app")
    assert mac_app_bundle("/usr/bin/python3") is None


def test_la_copia_de_codigo_fuente_sigue_con_git(app):
    from lot_bot.core.updater import Updater

    assert isinstance(app.updater, Updater)
