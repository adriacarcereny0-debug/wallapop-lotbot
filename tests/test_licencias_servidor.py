"""Licencias contra el servidor DE VERDAD (la web Next.js + Postgres).

No se ejecutan por defecto. Para lanzarlas:

    # 1. Web en marcha con una clave de firma de PRUEBAS (ver web/README.md)
    # 2. Desde la raíz del repositorio:
    LOT_BOT_TEST_LICENSE_SERVER=http://localhost:3100 \\
    LOT_BOT_TEST_LICENSE_DB=postgres://lotbot:lotbot@localhost:5432/lotbot_web \\
    python -m pytest tests/test_licencias_servidor.py

Crean licencias de prueba con `psql` (claves al azar) y comprueban activar,
renovar, suspender, revocar, caducar, límite de ordenadores, desvincular y
bloquear, con la app hablando HTTP con el servidor.
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import string
import subprocess
from datetime import UTC, datetime

import httpx
import pytest

from lot_bot.licensing.client import LicenseClient, TransientError
from lot_bot.licensing.config import LicenseConfig
from lot_bot.licensing.fingerprint import DeviceInfo
from lot_bot.licensing.manager import LicenseManager, LicenseState

SERVER = os.environ.get("LOT_BOT_TEST_LICENSE_SERVER", "")
DB = os.environ.get("LOT_BOT_TEST_LICENSE_DB", "")

pytestmark = pytest.mark.skipif(
    not (SERVER and DB and shutil.which("psql")),
    reason="Sin servidor de licencias de pruebas (LOT_BOT_TEST_LICENSE_SERVER / _DB).",
)


def sql(query: str, *args: str) -> str:
    """Ejecuta SQL con parámetros (variables de psql, nunca texto pegado)."""
    command = ["psql", DB, "-v", "ON_ERROR_STOP=1", "-Atq"]
    for index, value in enumerate(args, 1):
        command += ["-v", f"p{index}={value}"]
    return subprocess.run(
        command, input=query, capture_output=True, text=True, check=True
    ).stdout.strip()


def new_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "LOTB-" + "-".join(parts)


def create_license(*, plan: str = "mensual", kind: str = "pago", hours: float | None = 720) -> str:
    key = new_key()
    expires = "NULL" if hours is None else f"now() + make_interval(secs => {int(hours * 3600)})"
    sql(
        "INSERT INTO lotbot.licenses (key, kind, plan_id, max_devices, expires_at) "
        "SELECT :'p1', :'p2', id, max_devices, " + expires + " FROM lotbot.plans WHERE slug = :'p3';",
        key,
        kind,
        plan,
    )
    return key


def set_license(key: str, column: str, value: str) -> None:
    assert column in {"status", "expires_at"}
    sql(f"UPDATE lotbot.licenses SET {column} = :'p2' WHERE key = :'p1';", key, value)


def set_device(key: str, fingerprint: str, status: str) -> None:
    sql(
        "UPDATE lotbot.devices d SET status = :'p3' FROM lotbot.licenses l "
        "WHERE l.id = d.license_id AND l.key = :'p1' AND d.fingerprint = :'p2';",
        key,
        fingerprint,
        status,
    )


@pytest.fixture(scope="module")
def public_key() -> bytes:
    data = httpx.get(f"{SERVER}/api/v1/public-key", timeout=10).json()
    assert data["ok"], "El servidor de pruebas no tiene LICENSE_SIGNING_KEY."
    return base64.b64decode(data["public_key"])


def device(tag: str = "") -> DeviceInfo:
    return DeviceInfo(secrets.token_hex(32), f"PC-PRUEBA{tag}", "Windows 11")


def manager_for(folder, public_key: bytes, dev: DeviceInfo, server: str = SERVER) -> LicenseManager:
    config = LicenseConfig(server=server, public_keys=(public_key,))
    folder.mkdir(parents=True, exist_ok=True)
    return LicenseManager(folder, config=config, client=LicenseClient(server), device=dev)


def test_activar_renovar_y_comprobar_la_firma(temp_paths, public_key):
    key = create_license()
    m = manager_for(temp_paths.config, public_key, device())
    result = m.activate(key.lower())
    assert result.ok, result.message
    status = m.status()
    assert status.state is LicenseState.ACTIVE
    assert status.plan == "mensual" and status.seats == 1
    lease_left = status.lease_expires_at - datetime.now(UTC)
    assert 71.5 * 3600 < lease_left.total_seconds() <= 72 * 3600 + 60
    assert m.refresh().state is LicenseState.ACTIVE


def test_clave_que_no_existe(temp_paths, public_key):
    m = manager_for(temp_paths.config, public_key, device())
    result = m.activate(new_key())
    assert not result.ok and result.code == "LICENSE_NOT_FOUND"


def test_suspender_y_reactivar_desde_el_panel(temp_paths, public_key):
    key = create_license()
    m = manager_for(temp_paths.config, public_key, device())
    assert m.activate(key).ok
    set_license(key, "status", "suspendida")
    status = m.refresh()
    assert status.state is LicenseState.BLOCKED and status.code == "LICENSE_SUSPENDED"
    set_license(key, "status", "activa")
    assert m.refresh().state is LicenseState.ACTIVE


def test_revocar(temp_paths, public_key):
    key = create_license()
    m = manager_for(temp_paths.config, public_key, device())
    assert m.activate(key).ok
    set_license(key, "status", "revocada")
    assert m.refresh().code == "LICENSE_REVOKED"
    assert not m.activate(key).ok


def test_caducada_y_renovada(temp_paths, public_key):
    key = create_license()
    m = manager_for(temp_paths.config, public_key, device())
    assert m.activate(key).ok
    set_license(key, "expires_at", "2020-01-01T00:00:00Z")
    assert m.refresh().code == "LICENSE_EXPIRED"
    set_license(key, "expires_at", "2099-01-01T00:00:00Z")
    assert m.refresh().state is LicenseState.ACTIVE


def test_la_prueba_de_24h_no_pasa_de_su_caducidad(temp_paths, public_key):
    key = create_license(kind="prueba", plan="mensual", hours=2)
    m = manager_for(temp_paths.config, public_key, device())
    assert m.activate(key).ok
    status = m.status()
    assert status.is_trial
    # El pase no dura 72 h: termina cuando termina la prueba.
    assert abs((status.lease_expires_at - status.license_expires_at).total_seconds()) < 2


def test_limite_de_ordenadores_y_cambiar_de_ordenador(temp_paths, public_key):
    key = create_license(plan="mensual")
    first = manager_for(temp_paths.root / "pc1", public_key, device("1"))
    second = manager_for(temp_paths.root / "pc2", public_key, device("2"))
    assert first.activate(key).ok
    result = second.activate(key)
    assert not result.ok and result.code == "DEVICE_LIMIT"
    assert first.deactivate().ok
    assert first.status().state is LicenseState.NONE
    assert second.activate(key).ok


def test_plan_anual_admite_dos_ordenadores(temp_paths, public_key):
    key = create_license(plan="anual")
    a = manager_for(temp_paths.root / "a", public_key, device("A"))
    b = manager_for(temp_paths.root / "b", public_key, device("B"))
    c = manager_for(temp_paths.root / "c", public_key, device("C"))
    assert a.activate(key).ok and b.activate(key).ok
    assert c.activate(key).code == "DEVICE_LIMIT"


def test_el_admin_desvincula_o_bloquea_el_ordenador(temp_paths, public_key):
    key = create_license()
    dev = device()
    m = manager_for(temp_paths.config, public_key, dev)
    assert m.activate(key).ok
    set_device(key, dev.fingerprint, "desvinculado")
    assert m.refresh().code == "DEVICE_NOT_ACTIVATED"
    assert m.activate(key).ok  # la persona puede volver a activarlo (hay plaza)
    set_device(key, dev.fingerprint, "bloqueado")
    assert m.refresh().code == "DEVICE_BLOCKED"
    assert m.activate(key).code == "DEVICE_BLOCKED"


def test_servidor_caido_no_bloquea_una_licencia_activa(temp_paths, public_key):
    key = create_license()
    dev = device()
    m = manager_for(temp_paths.config, public_key, dev)
    assert m.activate(key).ok
    down = manager_for(temp_paths.config, public_key, dev, server="http://127.0.0.1:9")
    status = down.refresh()
    assert status.state is LicenseState.ACTIVE and status.offline
    with pytest.raises(TransientError):
        LicenseClient("http://127.0.0.1:9").refresh(key, dev)
