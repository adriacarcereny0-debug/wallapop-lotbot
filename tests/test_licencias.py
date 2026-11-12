"""Licencias: activación, pase firmado, renovación, sin conexión, bloqueo y cola.

El servidor se simula con un cliente falso que firma los pases igual que la web
(Ed25519, formato LBT1). Las pruebas contra el servidor de verdad (Next.js +
Postgres) están en tests/test_licencias_servidor.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from lot_bot.licensing.client import ServerReply, TransientError
from lot_bot.licensing.config import LicenseConfig, decode_public_key, load_config
from lot_bot.licensing.fingerprint import DeviceInfo, device_info
from lot_bot.licensing.guard import (
    LicensedService,
    LicenseRequiredError,
    guard_backend,
    publication_in_progress,
)
from lot_bot.licensing.lease import LeaseError, key_hash, verify_lease
from lot_bot.licensing.manager import (
    REFRESH_MAX_SECONDS,
    REFRESH_MIN_SECONDS,
    RETRY_BLOCKED_SECONDS,
    RETRY_OFFLINE_SECONDS,
    LicenseManager,
    LicenseState,
    normalize_key,
)

KEY = "LOTB-AB12-CD34-EF56"
HOUR = 3600
T0 = 1_800_000_000.0  # 2027-01-15


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class Signer:
    def __init__(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public_raw = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kid = hashlib.sha256(self.public_raw).hexdigest()[:8]

    def token(self, **fields) -> str:
        payload = {"v": 1, "typ": "lotbot-lease", "kid": self.kid, **fields}
        body = "LBT1." + b64url(json.dumps(payload).encode())
        return body + "." + b64url(self.private.sign(body.encode()))


@dataclass
class FakeServer:
    """Hace de servidor de licencias (lo que contestaría la web)."""

    signer: Signer
    clock: list[float]
    lease_hours: float = 72
    license_expires: float | None = None
    kind: str = "suscripcion"
    status: str = "activa"  # activa | suspendida | revocada | caducada | inexistente
    device_status: str = "activo"  # activo | bloqueado | desvinculado
    offline: bool = False
    seats: int = 1
    activations: int = 0
    calls: list[str] = field(default_factory=list)
    token_override: str | None = None
    server_skew: float = 0.0

    def _now(self) -> float:
        return self.clock[0] + self.server_skew

    def _error(self) -> ServerReply | None:
        if self.offline:
            raise TransientError("sin red")
        if self.status == "inexistente":
            return ServerReply(False, "LICENSE_NOT_FOUND", "Esa clave de licencia no existe.")
        if self.status == "revocada":
            return ServerReply(False, "LICENSE_REVOKED", "Esta licencia ha sido revocada.")
        if self.status == "suspendida":
            return ServerReply(False, "LICENSE_SUSPENDED", "Esta licencia está suspendida (impago).")
        if self.status == "caducada" or (self.license_expires and self._now() >= self.license_expires):
            return ServerReply(False, "LICENSE_EXPIRED", "La licencia ha caducado.")
        if self.device_status == "bloqueado":
            return ServerReply(False, "DEVICE_BLOCKED", "Este ordenador está bloqueado.")
        return None

    def _lease(self, key: str, device: DeviceInfo) -> ServerReply:
        now = self._now()
        exp = now + self.lease_hours * HOUR
        if self.license_expires:
            exp = min(exp, self.license_expires)
        token = self.token_override or self.signer.token(
            lic=7,
            kh=key_hash(key),
            dev=device.fingerprint,
            kind=self.kind,
            plan="mensual",
            seats=self.seats,
            lic_exp=int(self.license_expires) if self.license_expires else None,
            iat=int(now),
            exp=int(exp),
        )
        iso = datetime.fromtimestamp(now, tz=UTC).isoformat()
        info = {
            "kind": self.kind,
            "plan": "mensual",
            "status": "activa",
            "expires_at": (
                datetime.fromtimestamp(self.license_expires, tz=UTC).isoformat()
                if self.license_expires
                else None
            ),
            "max_devices": self.seats,
            "devices_in_use": 1,
        }
        return ServerReply(True, token=token, server_time=iso, license=info)

    def activate(self, key, device):
        self.calls.append("activate")
        error = self._error()
        if error:
            return error
        if self.device_status != "activo" and self.activations >= self.seats:
            return ServerReply(False, "DEVICE_LIMIT", "Ya está activada en 1 ordenador.")
        self.device_status = "activo"
        self.activations += 1
        return self._lease(key, device)

    def refresh(self, key, device):
        self.calls.append("refresh")
        error = self._error()
        if error:
            return error
        if self.device_status == "desvinculado":
            return ServerReply(False, "DEVICE_NOT_ACTIVATED", "Este ordenador no está activado.")
        return self._lease(key, device)

    def deactivate(self, key, device):
        self.calls.append("deactivate")
        if self.offline:
            raise TransientError("sin red")
        self.device_status = "desvinculado"
        return ServerReply(True)


DEVICE = DeviceInfo(fingerprint="a" * 64, name="PC-PRUEBA", os="Windows 11")


@pytest.fixture()
def clock():
    return [T0]


@pytest.fixture()
def signer():
    return Signer()


@pytest.fixture()
def server(signer, clock):
    return FakeServer(signer, clock)


def make_manager(temp_paths, server, clock, signer, **kwargs):
    import random

    config = LicenseConfig(server="https://licencias.test", public_keys=(signer.public_raw,))
    return LicenseManager(
        temp_paths.config,
        config=kwargs.get("config", config),
        client=server,
        device=kwargs.get("device", DEVICE),
        clock=lambda: clock[0],
        rng=random.Random(1),
    )


@pytest.fixture()
def manager(temp_paths, server, clock, signer):
    return make_manager(temp_paths, server, clock, signer)


# ---------------------------------------------------------------------------
# Configuración y huella
# ---------------------------------------------------------------------------
def test_sin_clave_publica_no_se_exige_licencia(temp_paths, monkeypatch):
    monkeypatch.delenv("LOT_BOT_LICENSE_PUBLIC_KEY", raising=False)
    manager = LicenseManager(temp_paths.config, config=load_config())
    status = manager.status()
    assert status.state is LicenseState.DISABLED
    assert status.allowed and manager.allows_real_use()


def test_en_el_programa_instalado_no_se_puede_cambiar_la_clave_publica(monkeypatch, signer):
    import lot_bot.licensing.config as config_module

    monkeypatch.setenv("LOT_BOT_LICENSE_PUBLIC_KEY", base64.b64encode(signer.public_raw).decode())
    monkeypatch.setenv("LOT_BOT_LICENSE_SERVER", "http://localhost:9")
    assert load_config().enforced  # desde el código fuente sí (pruebas)
    monkeypatch.setattr(config_module, "is_frozen", lambda: True)
    frozen = load_config()
    assert frozen.public_keys == ()  # el ejecutable solo usa las claves de dentro
    assert frozen.server == "https://www.lotbot.es"


def test_clave_publica_mal_escrita_se_ignora():
    assert decode_public_key("no-es-base64!!") is None
    assert decode_public_key(base64.b64encode(b"corta").decode()) is None


def test_huella_estable_anonima_y_valida(temp_paths):
    a = device_info(temp_paths.config, machine_id="1234-ABCD")
    b = device_info(temp_paths.config, machine_id="1234-abcd")
    other = device_info(temp_paths.config, machine_id="9999")
    assert a.fingerprint == b.fingerprint != other.fingerprint
    assert len(a.fingerprint) == 64 and "1234" not in a.fingerprint
    # Cumple lo que acepta el servidor: [A-Za-z0-9_-]{16,128}.
    import re

    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", a.fingerprint)


def test_huella_de_este_sistema(temp_paths):
    """En Windows/macOS/Linux sale siempre una huella, y la misma dos veces."""
    first = device_info(temp_paths.config)
    second = device_info(temp_paths.config)
    assert first.fingerprint == second.fingerprint
    assert first.os


@pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin"),
    reason="Solo en Windows y Mac (lo ejecuta el CI de los dos sistemas).",
)
def test_windows_y_mac_dan_su_identificador_de_equipo():
    from lot_bot.licensing.fingerprint import system_machine_id

    assert system_machine_id()


def test_lectura_del_identificador_en_mac(monkeypatch):
    import subprocess as sp

    import lot_bot.licensing.fingerprint as fp

    salida = '+-o J316sAP  <class IOPlatformExpertDevice>\n    "IOPlatformUUID" = "0A1B2C3D-1111-2222-3333-444455556666"\n'
    monkeypatch.setattr(sp, "run", lambda *a, **k: sp.CompletedProcess(a, 0, salida, ""))
    assert fp._mac_platform_uuid() == "0A1B2C3D-1111-2222-3333-444455556666"
    monkeypatch.setattr(sp, "run", lambda *a, **k: sp.CompletedProcess(a, 0, "", ""))
    assert fp._mac_platform_uuid() is None


def test_sin_identificador_del_sistema_se_crea_uno_propio(temp_paths, monkeypatch):
    import lot_bot.licensing.fingerprint as fp

    monkeypatch.setattr(fp, "system_machine_id", lambda: None)
    a = fp.device_info(temp_paths.config)
    b = fp.device_info(temp_paths.config)
    assert a.fingerprint == b.fingerprint
    assert (temp_paths.config / "device_id").is_file()


def test_normalizar_la_clave():
    assert normalize_key(" lotb ab12 cd34 ef56 ") == KEY
    assert normalize_key("lotbab12cd34ef56") == KEY
    assert normalize_key(KEY.lower()) == KEY


# ---------------------------------------------------------------------------
# Pase firmado
# ---------------------------------------------------------------------------
def test_pase_valido_y_manipulaciones(signer):
    token = signer.token(lic=1, kh=key_hash(KEY), dev=DEVICE.fingerprint, kind="suscripcion",
                         plan="mensual", seats=1, lic_exp=None, iat=int(T0), exp=int(T0 + 72 * HOUR))
    lease = verify_lease(token, (signer.public_raw,), license_key=KEY, fingerprint=DEVICE.fingerprint)
    assert lease.expires_at == int(T0 + 72 * HOUR)

    prefix, body, sig = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    data["exp"] += 365 * 24 * HOUR  # alargarlo a mano
    forged = f"{prefix}.{b64url(json.dumps(data).encode())}.{sig}"
    with pytest.raises(LeaseError, match="firma"):
        verify_lease(forged, (signer.public_raw,), license_key=KEY, fingerprint=DEVICE.fingerprint)
    with pytest.raises(LeaseError, match="firma"):
        verify_lease(token, (Signer().public_raw,), license_key=KEY, fingerprint=DEVICE.fingerprint)
    with pytest.raises(LeaseError, match="otra clave"):
        verify_lease(token, (signer.public_raw,), license_key="LOTB-ZZZZ-ZZZZ-ZZZZ", fingerprint=DEVICE.fingerprint)
    with pytest.raises(LeaseError, match="otro ordenador"):
        verify_lease(token, (signer.public_raw,), license_key=KEY, fingerprint="b" * 64)
    for broken in ("", "LBT1.x", "XXX.a.b", "LBT1.@@.##"):
        with pytest.raises(LeaseError):
            verify_lease(broken, (signer.public_raw,), license_key=KEY, fingerprint=DEVICE.fingerprint)


def test_el_pase_de_python_es_el_mismo_formato_que_el_de_la_web(signer):
    """Mismo cálculo de huella de clave que web/src/lib/signing.ts (sha256, 16 hex)."""
    assert key_hash(" lotb-ab12-cd34-ef56 ") == hashlib.sha256(KEY.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Activación
# ---------------------------------------------------------------------------
def test_sin_activar_no_se_puede_usar_wallapop_real(manager):
    status = manager.status()
    assert status.state is LicenseState.NONE
    assert not status.allowed


def test_activar_bien(manager, temp_paths):
    result = manager.activate("lotb-ab12-cd34-ef56")
    assert result.ok, result.message
    status = manager.status()
    assert status.state is LicenseState.ACTIVE and status.allowed
    assert status.lease_expires_at == datetime.fromtimestamp(T0 + 72 * HOUR, tz=UTC)
    assert status.key_masked.startswith("LOTB-") and "AB12" not in status.key_masked
    # La clave no se guarda en claro.
    raw = (temp_paths.config / "licencia.json").read_text()
    assert KEY not in raw and "AB12" not in raw


def test_activar_con_formato_incorrecto_no_llama_al_servidor(manager, server):
    result = manager.activate("hola")
    assert not result.ok and "LOTB-XXXX" in result.message
    assert server.calls == []


def test_activar_sin_conexion(manager, server):
    server.offline = True
    result = manager.activate(KEY)
    assert not result.ok and result.code == "OFFLINE"
    assert "conexión" in result.message
    assert manager.status().state is LicenseState.NONE


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"status": "inexistente"}, "LICENSE_NOT_FOUND"),
        ({"status": "revocada"}, "LICENSE_REVOKED"),
        ({"status": "suspendida"}, "LICENSE_SUSPENDED"),
        ({"status": "caducada"}, "LICENSE_EXPIRED"),
        ({"device_status": "bloqueado"}, "DEVICE_BLOCKED"),
    ],
)
def test_activar_con_errores_del_servidor(manager, server, change, code):
    for name, value in change.items():
        setattr(server, name, value)
    result = manager.activate(KEY)
    assert not result.ok and result.code == code and result.message
    assert not manager.status().allowed


def test_activar_en_un_segundo_ordenador_con_plan_de_uno(temp_paths, server, clock, signer):
    first = make_manager(temp_paths, server, clock, signer)
    assert first.activate(KEY).ok
    server.device_status = "desvinculado"  # el otro ordenador ocupa la plaza
    second = make_manager(temp_paths, server, clock, signer, device=DeviceInfo("b" * 64, "OTRO", "macOS"))
    result = second.activate(KEY)
    assert not result.ok and result.code == "DEVICE_LIMIT"


def test_pase_firmado_con_otra_clave_no_se_acepta(manager, server):
    impostor = Signer()
    server.token_override = impostor.token(lic=7, kh=key_hash(KEY), dev=DEVICE.fingerprint,
                                           kind="suscripcion", plan="x", seats=1, lic_exp=None,
                                           iat=int(T0), exp=int(T0 + 72 * HOUR))
    result = manager.activate(KEY)
    assert not result.ok and result.code == "LEASE_INVALID"
    assert manager.status().state is LicenseState.NONE  # no se guarda nada


# ---------------------------------------------------------------------------
# Renovación y sin conexión
# ---------------------------------------------------------------------------
def test_renovacion_cada_4_a_6_horas(manager, server, clock):
    manager.activate(KEY)
    nxt = manager._data.next_refresh
    assert T0 + REFRESH_MIN_SECONDS <= nxt <= T0 + REFRESH_MAX_SECONDS
    clock[0] = T0 + 3 * HOUR
    manager.refresh_if_due()
    assert server.calls == ["activate"]  # aún no toca
    clock[0] = nxt + 1
    manager.refresh_if_due()
    assert server.calls == ["activate", "refresh"]
    assert manager.status().lease_expires_at.timestamp() == pytest.approx(nxt + 1 + 72 * HOUR, abs=1)


def test_sin_conexion_sigue_3_dias_y_luego_bloquea(manager, server, clock):
    manager.activate(KEY)
    server.offline = True
    clock[0] = T0 + 5 * HOUR
    status = manager.refresh()
    assert status.state is LicenseState.ACTIVE and status.offline
    assert manager._data.next_refresh == pytest.approx(clock[0] + RETRY_OFFLINE_SECONDS)
    clock[0] = T0 + 71.9 * HOUR
    assert manager.status().allowed
    clock[0] = T0 + 72 * HOUR + 1
    status = manager.status()
    assert status.state is LicenseState.BLOCKED and status.code == "OFFLINE_TOO_LONG"
    # Vuelve la conexión: sigue solo.
    server.offline = False
    status = manager.refresh()
    assert status.state is LicenseState.ACTIVE and not status.offline


def test_el_pase_sobrevive_a_cerrar_y_abrir_sin_conexion(temp_paths, server, clock, signer):
    assert make_manager(temp_paths, server, clock, signer).activate(KEY).ok
    server.offline = True
    clock[0] = T0 + 48 * HOUR
    reopened = make_manager(temp_paths, server, clock, signer)
    assert reopened.status().state is LicenseState.ACTIVE
    assert reopened.refresh().allowed  # sin red, sigue con el pase


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"status": "suspendida"}, "LICENSE_SUSPENDED"),
        ({"status": "revocada"}, "LICENSE_REVOKED"),
        ({"status": "caducada"}, "LICENSE_EXPIRED"),
        ({"device_status": "bloqueado"}, "DEVICE_BLOCKED"),
        ({"device_status": "desvinculado"}, "DEVICE_NOT_ACTIVATED"),
        ({"status": "inexistente"}, "LICENSE_NOT_FOUND"),
    ],
)
def test_respuesta_definitiva_bloquea_al_momento(manager, server, clock, change, code):
    manager.activate(KEY)
    for name, value in change.items():
        setattr(server, name, value)
    clock[0] = T0 + HOUR
    status = manager.refresh()
    assert status.state is LicenseState.BLOCKED and status.code == code
    assert status.message
    assert manager._data.token is None  # el pase anterior ya no vale
    assert manager._data.next_refresh == pytest.approx(clock[0] + RETRY_BLOCKED_SECONDS)


def test_suspendida_y_reactivada_vuelve_sola(manager, server, clock):
    manager.activate(KEY)
    server.status = "suspendida"
    clock[0] = T0 + HOUR
    assert manager.refresh().code == "LICENSE_SUSPENDED"
    server.status = "activa"
    clock[0] += RETRY_BLOCKED_SECONDS + 1
    assert manager.refresh_if_due().state is LicenseState.ACTIVE


def test_caduca_dentro_del_pase_sin_necesidad_de_red(manager, server, clock):
    server.license_expires = T0 + 10 * HOUR
    server.kind = "prueba"
    manager.activate(KEY)
    server.offline = True
    clock[0] = T0 + 9 * HOUR
    assert manager.status().allowed
    clock[0] = T0 + 10 * HOUR
    status = manager.status()
    assert status.state is LicenseState.BLOCKED and status.code == "TRIAL_EXPIRED"
    assert "prueba" in status.message.lower()


def test_errores_pasajeros_del_servidor_no_bloquean(manager, server, clock):
    manager.activate(KEY)

    class Flaky:
        def refresh(self, *a):
            return ServerReply(False, "RATE_LIMITED", "Demasiados intentos.")

    manager.client = Flaky()
    clock[0] = T0 + 5 * HOUR
    assert manager.refresh().allowed


# ---------------------------------------------------------------------------
# Reloj
# ---------------------------------------------------------------------------
def test_atrasar_el_reloj_bloquea_hasta_comprobar(manager, server, clock):
    manager.activate(KEY)
    clock[0] = T0 + 60 * HOUR  # usa el programa 60 h
    assert manager.status().allowed
    manager._save()
    clock[0] = T0 + 1 * HOUR  # y atrasa el reloj para alargar el pase
    status = manager.status()
    assert status.state is LicenseState.BLOCKED and status.code == "CLOCK_TAMPERED"
    # Al comprobar con el servidor, la hora del servidor manda.
    server.server_skew = 59 * HOUR  # el servidor sabe que en realidad son T0+60h
    assert manager.refresh().state is LicenseState.ACTIVE


def test_atrasar_el_reloj_se_nota_tras_reiniciar(temp_paths, server, clock, signer):
    first = make_manager(temp_paths, server, clock, signer)
    first.activate(KEY)
    clock[0] = T0 + 50 * HOUR
    first.status()  # guarda la hora vista (cada 5 min como mucho)
    clock[0] = T0 + 2 * HOUR
    again = make_manager(temp_paths, server, clock, signer)
    server.offline = True
    assert again.status().code == "CLOCK_TAMPERED"


def test_reloj_del_pc_atrasado_de_fabrica_se_corrige_con_el_servidor(manager, server, clock):
    server.server_skew = 3 * 24 * HOUR  # el PC va 3 días atrasado
    result = manager.activate(KEY)
    assert result.ok
    assert manager.status().state is LicenseState.ACTIVE


# ---------------------------------------------------------------------------
# Fichero manipulado y desvincular
# ---------------------------------------------------------------------------
def test_fichero_de_licencia_manipulado(temp_paths, manager, server, clock, signer):
    manager.activate(KEY)
    path = temp_paths.config / "licencia.json"
    data = json.loads(path.read_text())
    prefix, body, sig = data["token"].split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["exp"] = int(T0 + 3650 * 24 * HOUR)
    data["token"] = f"{prefix}.{b64url(json.dumps(payload).encode())}.{sig}"
    path.write_text(json.dumps(data))
    reopened = make_manager(temp_paths, server, clock, signer)
    assert reopened.status().code == "LEASE_INVALID"


def test_fichero_dañado_no_rompe_nada(temp_paths, server, clock, signer):
    (temp_paths.config / "licencia.json").write_text("{esto no es json")
    m = make_manager(temp_paths, server, clock, signer)
    assert m.status().state is LicenseState.NONE
    assert m.activate(KEY).ok


def test_copiar_el_fichero_a_otro_ordenador_no_sirve(temp_paths, manager, server, clock, signer):
    manager.activate(KEY)
    other = make_manager(temp_paths, server, clock, signer, device=DeviceInfo("c" * 64, "OTRO", "macOS"))
    assert other.status().code == "LEASE_INVALID"


def test_desvincular(manager, server):
    manager.activate(KEY)
    server.offline = True
    result = manager.deactivate()
    assert not result.ok and result.code == "OFFLINE"
    assert manager.status().allowed  # sin red no se pierde nada
    server.offline = False
    result = manager.deactivate()
    assert result.ok
    assert manager.status().state is LicenseState.NONE
    assert server.device_status == "desvinculado"


def test_avisos_al_cambiar_de_estado(manager, server, clock):
    seen = []
    manager.listeners.append(lambda s: seen.append((s.state, s.code)))
    manager.activate(KEY)
    server.status = "revocada"
    manager.refresh()
    manager.refresh()  # mismo estado: no se repite el aviso
    assert seen == [(LicenseState.ACTIVE, ""), (LicenseState.BLOCKED, "LICENSE_REVOKED")]


# ---------------------------------------------------------------------------
# Candado delante de Wallapop
# ---------------------------------------------------------------------------
class FakeService:
    is_mock = False
    user_gate = None

    def __init__(self):
        self.created = []

    def create_item(self, ref, draft):
        self.created.append(draft)
        return "ok"

    def list_items(self, ref):
        return ["anuncio"]


def test_candado_bloquea_escribir_pero_no_leer():
    allowed = [False]
    inner = FakeService()
    service = LicensedService(inner, lambda: allowed[0], lambda: "Licencia caducada.")
    assert service.list_items("c1") == ["anuncio"]
    with pytest.raises(LicenseRequiredError) as exc:
        service.create_item("c1", "x")
    assert "Licencia" in exc.value.user_message
    assert inner.created == []
    allowed[0] = True
    assert service.create_item("c1", "x") == "ok"
    # Atributos que pone la cola llegan al servicio de verdad.
    service.user_gate = "puerta"
    assert inner.user_gate == "puerta"
    assert service.is_mock is False


def test_lo_que_ya_se_esta_publicando_termina():
    inner = FakeService()
    service = LicensedService(inner, lambda: False, lambda: "caducada")
    with publication_in_progress():
        assert service.create_item("c1", "x") == "ok"
    with pytest.raises(LicenseRequiredError):
        service.create_item("c1", "y")


def test_el_modo_demo_no_lleva_candado(app, manager):
    backend = app.backend
    assert backend.demo
    assert guard_backend(backend, manager).service is backend.service
    assert not isinstance(app.wallapop, LicensedService)


# ---------------------------------------------------------------------------
# Cola de publicación
# ---------------------------------------------------------------------------
def _real_mode(app, manager):
    """La app de pruebas va en DEMO: se simula Wallapop real con licencia."""
    app.backend.demo = False
    app.license = manager
    guard_backend(app.backend, manager)
    manager.listeners.append(lambda s: app.publish_queue.license_restored() if s.allowed else None)


def _refs(app):
    return [a.internal_ref for a in app.accounts.list_accounts() if a.is_connected]


def test_cola_se_pausa_al_caducar_y_sigue_sola_al_renovar(app, manager, server, clock):
    queue = app.publish_queue
    # (Se crea la cola antes de simular el modo real: las cuentas son de prueba.)
    job = queue.enqueue_master(None, _refs(app)[:3], copies=3, generate_images=False)
    _real_mode(app, manager)
    manager.activate(KEY)
    assert queue.run_once()  # primer anuncio publicado
    assert len([t for t in queue.progress(job).tasks if t["estado"] == "published"]) == 1

    server.status = "suspendida"
    manager.refresh()
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "paused"
    assert "Licencia no activa" in (progress.pause_reason or "")
    assert len([t for t in progress.tasks if t["estado"] == "published"]) == 1
    assert len([t for t in progress.tasks if t["estado"] == "pending"]) == 2

    server.status = "activa"
    clock[0] += RETRY_BLOCKED_SECONDS + 1
    manager.refresh_if_due()  # al reactivarse, la cola sigue sola
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "completed"
    assert len([t for t in progress.tasks if t["estado"] == "published"]) == 3


def test_si_caduca_a_mitad_de_publicar_ese_anuncio_termina(app, manager, server, clock):
    queue = app.publish_queue
    job = queue.enqueue_master(None, _refs(app)[:2], copies=2, generate_images=False)
    _real_mode(app, manager)
    manager.activate(KEY)
    original = app.master_ads.publish_single

    def caduca_a_mitad(*args, **kwargs):
        server.status = "revocada"
        manager.refresh()
        assert not manager.allows_real_use()
        return original(*args, **kwargs)

    app.master_ads.publish_single = caduca_a_mitad
    queue.run_once()
    app.master_ads.publish_single = original
    queue.run_until_idle()
    progress = queue.progress(job)
    assert [t["estado"] for t in progress.tasks] == ["published", "pending"]
    assert progress.status == "paused"


def test_sin_licencia_la_cola_no_empieza_y_los_datos_siguen(app, manager):
    queue = app.publish_queue
    antes = len(app.accounts.list_accounts())
    job = queue.enqueue_master(None, _refs(app)[:2], copies=2, generate_images=False)
    _real_mode(app, manager)
    queue.run_until_idle()
    progress = queue.progress(job)
    assert progress.status == "paused"
    assert all(t["estado"] == "pending" for t in progress.tasks)
    assert len(app.accounts.list_accounts()) == antes
    # Leer sigue funcionando (tus anuncios), publicar no.
    ref = _refs(app)[0]
    app.wallapop.list_items(ref)
    from lot_bot.wallapop.dto import ItemDraft

    with pytest.raises(LicenseRequiredError):
        app.wallapop.create_item(ref, ItemDraft(title="x", description="y", price=1))


def test_en_demo_la_cola_publica_sin_licencia(app, manager):
    app.license = manager  # sin activar
    queue = app.publish_queue
    job = queue.enqueue_master(None, _refs(app)[:2], copies=2, generate_images=False)
    queue.run_until_idle()
    assert queue.progress(job).status == "completed"


def test_la_app_arranca_con_el_gestor_de_licencias(app):
    assert app.license is not None
    assert app.license.status().allowed  # esta versión aún no la exige


# ---------------------------------------------------------------------------
# La clave de producción que va dentro del programa
# ---------------------------------------------------------------------------
@pytest.mark.licencia_real
def test_el_programa_lleva_la_clave_publica_de_produccion(monkeypatch):
    import lot_bot.licensing.config as config_module

    monkeypatch.delenv("LOT_BOT_LICENSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LOT_BOT_LICENSE_SERVER", raising=False)
    config = load_config()
    assert config.enforced
    assert config.server == "https://www.lotbot.es"
    assert [hashlib.sha256(k).hexdigest()[:8] for k in config.public_keys] == ["f9607729"]
    # En el programa instalado no se puede cambiar por otra.
    monkeypatch.setattr(config_module, "is_frozen", lambda: True)
    monkeypatch.setenv("LOT_BOT_LICENSE_PUBLIC_KEY", base64.b64encode(Signer().public_raw).decode())
    monkeypatch.setenv("LOT_BOT_LICENSE_SERVER", "http://127.0.0.1:9")
    frozen = load_config()
    assert [hashlib.sha256(k).hexdigest()[:8] for k in frozen.public_keys] == ["f9607729"]
    assert frozen.server == "https://www.lotbot.es"


@pytest.mark.licencia_real
def test_con_la_clave_real_el_demo_sigue_libre_y_wallapop_real_pide_licencia(app):
    from lot_bot.licensing import LicenseManager

    manager = LicenseManager(app.paths.config)
    assert manager.enforced
    assert manager.status().state is LicenseState.NONE
    # DEMO: sin candado.
    assert app.demo_mode and not isinstance(app.wallapop, LicensedService)
    # Wallapop real: con candado (y sin licencia no deja publicar).
    app.backend.demo = False
    guard_backend(app.backend, manager)
    assert isinstance(app.wallapop, LicensedService)
    from lot_bot.wallapop.dto import ItemDraft

    with pytest.raises(LicenseRequiredError):
        app.wallapop.create_item("c1", ItemDraft(title="x", description="y", price=1))
