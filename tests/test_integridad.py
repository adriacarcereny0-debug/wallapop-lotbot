"""Comprobación de la instalación: lista firmada de huellas de los ficheros
oficiales contra los ficheros de este ordenador. Solo informa."""

from __future__ import annotations

import base64
import hashlib
import json
import random

import httpx
import pytest

from lot_bot.licensing.config import LicenseConfig
from lot_bot.licensing.integrity import check_installation, compare, installation_root
from lot_bot.licensing.manager import LicenseManager
from tests.test_licencias import DEVICE, KEY, T0, FakeServer, Signer

EXE = b"MZ ejecutable oficial de LOT Bot"


def signed(signer: Signer, **fields) -> str:
    payload = {"v": 1, "typ": "lotbot-integrity", "kid": signer.kid, **fields}
    body = "LBT1." + base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return body + "." + base64.urlsafe_b64encode(signer.private.sign(body.encode())).rstrip(b"=").decode()


@pytest.fixture()
def env(temp_paths, tmp_path):
    clock = [T0]
    signer = Signer()
    manager = LicenseManager(
        temp_paths.config,
        config=LicenseConfig("https://licencias.test", (signer.public_raw,)),
        client=FakeServer(signer, clock), device=DEVICE, clock=lambda: clock[0], rng=random.Random(1),
    )
    assert manager.activate(KEY).ok
    root = tmp_path / "LOT Bot"
    root.mkdir()
    (root / "LOT-Bot.exe").write_bytes(EXE)
    state = {"files": {"LOT-Bot.exe": hashlib.sha256(EXE).hexdigest()}, "reports": [], "token": None}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/api/v1/integrity":
            token = state["token"] or signed(signer, ver="1.0.0", plat="windows-x64", files=state["files"],
                                             dev=DEVICE.fingerprint, iat=int(T0), exp=int(T0) + 3600)
            return httpx.Response(200, json={"ok": True, "token": token})
        state["reports"].append(body["result"])
        return httpx.Response(200, json={"ok": True})

    def run():
        return check_installation(manager, "windows-x64", root, version="1.0.0",
                                  transport=httpx.MockTransport(handler), clock=lambda: clock[0])

    return run, state, root, signer


def test_instalacion_oficial(env):
    run, state, _, _ = env
    assert run().state == "correcta"
    assert state["reports"] == ["correcta"]


def test_ejecutable_cambiado_se_detecta_y_se_cuenta(env):
    run, state, root, _ = env
    (root / "LOT-Bot.exe").write_bytes(EXE + b" parche")
    result = run()
    assert result.state == "modificada" and "LOT-Bot.exe" in result.detail
    assert state["reports"] == ["modificada"]
    assert (root / "LOT-Bot.exe").exists()  # solo informa: no borra nada


def test_fichero_que_falta(env):
    run, state, root, _ = env
    (root / "LOT-Bot.exe").unlink()
    assert run().state == "modificada"


def test_lista_firmada_por_otro_no_vale(env):
    run, state, _, _ = env
    state["token"] = signed(Signer(), ver="1.0.0", plat="windows-x64", files={"LOT-Bot.exe": "0" * 64},
                            dev=DEVICE.fingerprint, iat=int(T0), exp=int(T0) + 3600)
    assert run().state == "sin_datos"
    assert state["reports"] == []


def test_lista_de_otra_version_u_ordenador_no_vale(env):
    run, state, _, signer = env
    state["token"] = signed(signer, ver="9.9.9", plat="windows-x64", files=state["files"],
                            dev=DEVICE.fingerprint, iat=int(T0), exp=int(T0) + 3600)
    assert run().state == "sin_datos"
    state["token"] = signed(signer, ver="1.0.0", plat="windows-x64", files=state["files"],
                            dev="b" * 64, iat=int(T0), exp=int(T0) + 3600)
    assert run().state == "sin_datos"


def test_rutas_fuera_de_la_instalacion_no_se_leen(tmp_path):
    (tmp_path / "secreto.txt").write_text("x")
    inside = tmp_path / "app"
    inside.mkdir()
    assert compare(inside, {"../secreto.txt": "0" * 64, "/etc/passwd": "0" * 64}) == ["../secreto.txt", "/etc/passwd"]


def test_sin_conexion_no_pasa_nada(temp_paths, tmp_path):
    manager = LicenseManager(temp_paths.config, config=LicenseConfig("https://x", (b"x" * 32,)), device=DEVICE)
    assert check_installation(manager, "windows-x64", tmp_path).state == "sin_datos"  # sin licencia guardada


def test_carpeta_de_la_instalacion():
    root = installation_root("mac-arm64", "/Applications/LOT Bot.app/Contents/MacOS/LOT-Bot")
    assert root is not None and root.name == "LOT Bot.app"
    assert installation_root("mac-arm64", "/usr/bin/python3") is None
    assert installation_root("windows-x64", "/x/LOT Bot/LOT-Bot.exe").name == "LOT Bot"
