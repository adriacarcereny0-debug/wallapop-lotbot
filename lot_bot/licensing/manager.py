"""Estado de la licencia en este ordenador: activar, renovar, bloquear.

Reglas:

* Se renueva el pase cada 4-6 h (al azar, para no llamar todos a la vez).
* Sin conexión se sigue con el último pase mientras valga (72 h = 3 días).
* Una respuesta definitiva del servidor (caducada, suspendida, revocada,
  ordenador bloqueado o desvinculado) bloquea al momento. Aun bloqueado se
  sigue preguntando cada 30 min: si se renueva o se reactiva, vuelve solo.
* Si el reloj del ordenador va hacia atrás (más de 10 min respecto a la hora
  más alta vista) se bloquea hasta la siguiente comprobación con el servidor.
* Nada de esto toca los datos: solo decide si se puede actuar en Wallapop real.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from lot_bot.config.secrets import SecretsError, get_secret_box
from lot_bot.licensing.client import LicenseClient, ServerReply, TransientError
from lot_bot.licensing.config import LicenseConfig, load_config
from lot_bot.licensing.fingerprint import DeviceInfo, device_info
from lot_bot.licensing.lease import Lease, LeaseError, verify_lease
from lot_bot.licensing.store import LicenseStore, StoredLicense

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^LOTB-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

REFRESH_MIN_SECONDS = 4 * 3600
REFRESH_MAX_SECONDS = 6 * 3600
RETRY_OFFLINE_SECONDS = 15 * 60
RETRY_BLOCKED_SECONDS = 30 * 60
CLOCK_TOLERANCE_SECONDS = 10 * 60
#: Diferencias de reloj menores no se corrigen (ruido normal).
OFFSET_IGNORE_SECONDS = 120
#: Cada cuánto se guarda la «hora más alta vista» como mucho.
MAX_SEEN_SAVE_EVERY = 5 * 60


class LicenseState(str, Enum):
    DISABLED = "sin_exigir"  # esta versión no exige licencia
    NONE = "sin_licencia"  # no se ha activado ninguna
    ACTIVE = "activa"
    BLOCKED = "bloqueada"


MESSAGES = {
    "LICENSE_EXPIRED": "La licencia ha caducado. Renuévala para seguir publicando.",
    "TRIAL_EXPIRED": "La prueba gratis ha terminado. Elige un plan para seguir publicando.",
    "LICENSE_SUSPENDED": "La licencia está suspendida.",
    "LICENSE_REVOKED": "La licencia ha sido revocada.",
    "LICENSE_NOT_FOUND": "Esa clave de licencia no existe.",
    "DEVICE_BLOCKED": "Este ordenador está bloqueado para esta licencia. Contacta con soporte.",
    "DEVICE_NOT_ACTIVATED": (
        "Este ordenador se ha desvinculado de la licencia. Vuelve a activarla aquí si quieres "
        "usarla en este ordenador."
    ),
    "OFFLINE_TOO_LONG": (
        "LOT Bot lleva más de 3 días sin poder comprobar la licencia. Conéctate a Internet: "
        "en cuanto la compruebe, sigue solo."
    ),
    "CLOCK_TAMPERED": (
        "La fecha u hora del ordenador está atrasada. Corrígela (o conéctate a Internet) y "
        "LOT Bot seguirá solo."
    ),
    "LEASE_INVALID": "El permiso guardado de la licencia no es válido. Vuelve a activarla.",
}


def _ts(value: float | int | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _parse_iso(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def normalize_key(text: str) -> str:
    """Admite espacios, minúsculas y la clave sin guiones."""
    compact = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    if compact.startswith("LOTB") and len(compact) == 16:
        body = compact[4:]
        return f"LOTB-{body[0:4]}-{body[4:8]}-{body[8:12]}"
    return (text or "").strip().upper()


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    return key[:5] + "••••-••••-" + key[-4:]


@dataclass(frozen=True)
class LicenseStatus:
    state: LicenseState
    code: str = ""
    message: str = ""
    key_masked: str = ""
    kind: str = ""
    plan: str | None = None
    seats: int = 0
    license_expires_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_success: datetime | None = None
    offline: bool = False

    @property
    def allowed(self) -> bool:
        """¿Se puede actuar en Wallapop real?"""
        return self.state in (LicenseState.DISABLED, LicenseState.ACTIVE)

    @property
    def enforced(self) -> bool:
        return self.state is not LicenseState.DISABLED

    @property
    def is_trial(self) -> bool:
        return self.kind == "prueba"

    def signature(self) -> tuple:
        return (self.state, self.code, self.lease_expires_at, self.offline)


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    code: str = ""


class LicenseManager:
    def __init__(
        self,
        folder: Path,
        *,
        config: LicenseConfig | None = None,
        client: LicenseClient | None = None,
        device: DeviceInfo | None = None,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
    ) -> None:
        self.folder = Path(folder)
        self.config = config or load_config()
        self.client = client or LicenseClient(self.config.server)
        self._device = device
        self.clock = clock
        self._rng = rng or random.Random()
        self.store = LicenseStore(self.folder)
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._data = self.store.load()
        self._saved_max_seen = self._data.max_seen
        self._last_signature: tuple | None = None
        self.listeners: list[Callable[[LicenseStatus], None]] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    @property
    def device(self) -> DeviceInfo:
        if self._device is None:
            self._device = device_info(self.folder)
        return self._device

    @property
    def enforced(self) -> bool:
        return self.config.enforced

    def _key(self) -> str | None:
        if not self._data.key_enc:
            return None
        try:
            return get_secret_box().decrypt(self._data.key_enc)
        except SecretsError:
            logger.warning("No se puede leer la clave de licencia guardada: habrá que escribirla otra vez.")
            return None

    def stored_key(self) -> str | None:
        """La clave guardada (para rellenar la pantalla de activación)."""
        with self._lock:
            return self._key()

    def _save(self) -> None:
        self.store.save(self._data)
        self._saved_max_seen = self._data.max_seen

    def _now(self) -> float:
        """Hora corregida con la del servidor (si el reloj del PC va mal)."""
        return self.clock() + self._data.clock_offset

    # ------------------------------------------------------------------
    # Estado (local, sin red)
    # ------------------------------------------------------------------
    def status(self) -> LicenseStatus:
        with self._lock:
            return self._evaluate()

    def allows_real_use(self) -> bool:
        return self.status().allowed

    def _evaluate(self) -> LicenseStatus:
        if not self.config.enforced:
            return LicenseStatus(LicenseState.DISABLED)
        data = self._data
        key = self._key()
        if not key:
            return LicenseStatus(
                LicenseState.NONE,
                message="Activa tu licencia para publicar en Wallapop. El modo DEMO es gratis.",
            )
        now = self._now()
        base = {
            "key_masked": mask_key(key),
            "last_success": _ts(data.last_success),
            "offline": data.offline,
            "kind": str(data.info.get("kind") or ""),
            "plan": data.info.get("plan"),
            "seats": int(data.info.get("max_devices") or 0),
            "license_expires_at": _ts(_parse_iso(data.info.get("expires_at"))),
        }

        def blocked(code: str, message: str | None = None, **extra) -> LicenseStatus:
            return LicenseStatus(
                LicenseState.BLOCKED, code=code, message=message or MESSAGES.get(code, ""), **{**base, **extra}
            )

        # Reloj hacia atrás: no se puede fiar de la fecha del pase.
        if data.max_seen and now < data.max_seen - CLOCK_TOLERANCE_SECONDS:
            return blocked("CLOCK_TAMPERED")
        if data.blocked_code:
            return blocked(data.blocked_code, data.blocked_message or None)
        if not data.token:
            return LicenseStatus(
                LicenseState.NONE,
                message="Activa tu licencia para publicar en Wallapop. El modo DEMO es gratis.",
                **base,
            )
        try:
            lease = verify_lease(
                data.token,
                self.config.public_keys,
                license_key=key,
                fingerprint=self.device.fingerprint,
            )
        except LeaseError as exc:
            logger.warning("Pase de licencia no válido: %s", exc)
            return blocked("LEASE_INVALID")

        extra = {
            "kind": lease.kind,
            "plan": lease.plan,
            "seats": lease.seats,
            "lease_expires_at": _ts(lease.expires_at),
        }
        if lease.license_expires_at:
            extra["license_expires_at"] = _ts(lease.license_expires_at)
        if lease.issued_at > now + CLOCK_TOLERANCE_SECONDS:
            return blocked("CLOCK_TAMPERED", **extra)
        if lease.license_expires_at and now >= lease.license_expires_at:
            code = "TRIAL_EXPIRED" if lease.kind == "prueba" else "LICENSE_EXPIRED"
            return blocked(code, **extra)
        if now >= lease.expires_at:
            return blocked("OFFLINE_TOO_LONG", **extra)

        self._note_time(now)
        return LicenseStatus(LicenseState.ACTIVE, **{**base, **extra})

    def _note_time(self, now: float) -> None:
        if now > self._data.max_seen:
            self._data.max_seen = now
            if now - self._saved_max_seen >= MAX_SEEN_SAVE_EVERY:
                try:
                    self._save()
                except OSError:  # pragma: no cover
                    logger.debug("No se pudo guardar la hora vista.")

    # ------------------------------------------------------------------
    # Con el servidor
    # ------------------------------------------------------------------
    def _accept(self, key: str, reply: ServerReply) -> Lease:
        """Comprueba el pase recibido y lo guarda (con la lock tomada)."""
        lease = verify_lease(
            reply.token or "",
            self.config.public_keys,
            license_key=key,
            fingerprint=self.device.fingerprint,
        )
        local = self.clock()
        server = _parse_iso(reply.server_time) or float(lease.issued_at)
        offset = server - local
        data = self._data
        data.clock_offset = offset if abs(offset) > OFFSET_IGNORE_SECONDS else 0.0
        # La hora del servidor manda: si antes el reloj iba adelantado, se olvida.
        data.max_seen = local + data.clock_offset
        data.token = reply.token
        data.blocked_code = None
        data.blocked_message = None
        data.offline = False
        data.info = dict(reply.license or {})
        data.last_success = local
        data.last_attempt = local
        data.next_refresh = local + self._rng.uniform(REFRESH_MIN_SECONDS, REFRESH_MAX_SECONDS)
        return lease

    def activate(self, raw_key: str) -> ActionResult:
        """Activa la licencia en este ordenador (hace una llamada de red)."""
        if not self.config.enforced:
            return ActionResult(True, "Esta versión de LOT Bot no necesita licencia.")
        key = normalize_key(raw_key)
        if not KEY_RE.match(key):
            return ActionResult(
                False, "La clave tiene este formato: LOTB-XXXX-XXXX-XXXX.", "INVALID_FORMAT"
            )
        with self._refresh_lock:
            try:
                reply = self.client.activate(key, self.device)
            except TransientError as exc:
                logger.info("Activación sin conexión: %s", exc)
                return ActionResult(
                    False,
                    "No se ha podido conectar con el servidor de licencias. Revisa la conexión a "
                    "Internet y vuelve a probar.",
                    "OFFLINE",
                )
            if not reply.ok:
                return ActionResult(False, reply.message or MESSAGES.get(reply.code, "No se ha podido activar."), reply.code)
            with self._lock:
                previous = StoredLicense(**vars(self._data))
                try:
                    self._data.key_enc = get_secret_box().encrypt(key)
                    self._accept(key, reply)
                except LeaseError as exc:
                    self._data = previous
                    logger.error("El servidor ha devuelto un pase que no se puede comprobar: %s", exc)
                    return ActionResult(
                        False,
                        "El servidor ha contestado con un permiso que esta versión no reconoce. "
                        "Actualiza LOT Bot o contacta con soporte.",
                        "LEASE_INVALID",
                    )
                self._save()
                status = self._evaluate()
        logger.info("Licencia activada en este ordenador (%s).", status.kind or "licencia")
        self._notify(force=True)
        return ActionResult(True, self.describe(status))

    def refresh(self) -> LicenseStatus:
        """Renueva el pase. Sin red, sigue con el que hay."""
        if not self.config.enforced:
            return self.status()
        with self._refresh_lock:
            with self._lock:
                key = self._key()
            if not key:
                return self.status()
            try:
                reply = self.client.refresh(key, self.device)
            except TransientError as exc:
                logger.info("No se ha podido renovar la licencia ahora: %s", exc)
                with self._lock:
                    now = self.clock()
                    self._data.offline = True
                    self._data.last_attempt = now
                    self._data.next_refresh = now + RETRY_OFFLINE_SECONDS
                    self._save()
                self._notify()
                return self.status()
            with self._lock:
                now = self.clock()
                if reply.ok:
                    try:
                        self._accept(key, reply)
                    except LeaseError as exc:
                        logger.error("Pase renovado no válido: %s", exc)
                        self._data.offline = True
                        self._data.last_attempt = now
                        self._data.next_refresh = now + RETRY_OFFLINE_SECONDS
                else:
                    if reply.code in ("RATE_LIMITED", "INVALID_REQUEST", "TOO_MANY_CHANGES"):
                        self._data.next_refresh = now + RETRY_OFFLINE_SECONDS
                    else:
                        logger.warning("Licencia bloqueada por el servidor: %s", reply.code)
                        self._data.blocked_code = reply.code
                        self._data.blocked_message = reply.message or None
                        self._data.token = None
                        if reply.license:
                            self._data.info = dict(reply.license)
                        self._data.next_refresh = now + RETRY_BLOCKED_SECONDS
                    self._data.offline = False
                    self._data.last_attempt = now
                self._save()
        self._notify()
        return self.status()

    def refresh_if_due(self) -> LicenseStatus:
        with self._lock:
            due = self.config.enforced and bool(self._data.key_enc) and (
                self.clock() >= self._data.next_refresh
                or self.clock() + CLOCK_TOLERANCE_SECONDS < self._data.last_attempt
            )
        if due:
            return self.refresh()
        self._notify()
        return self.status()

    def deactivate(self) -> ActionResult:
        """Libera este ordenador (para usar la licencia en otro)."""
        with self._refresh_lock:
            with self._lock:
                key = self._key()
            if not key:
                self.forget()
                return ActionResult(True, "Este ordenador no tenía ninguna licencia activada.")
            try:
                reply = self.client.deactivate(key, self.device)
            except TransientError:
                return ActionResult(
                    False,
                    "Para desvincular este ordenador hace falta conexión a Internet. Vuelve a "
                    "probar en un momento.",
                    "OFFLINE",
                )
            if not reply.ok and reply.code not in ("DEVICE_NOT_ACTIVATED", "LICENSE_NOT_FOUND"):
                return ActionResult(False, reply.message or "No se ha podido desvincular.", reply.code)
            self.forget()
        return ActionResult(
            True, "Ordenador desvinculado. Ya puedes activar la licencia en otro ordenador."
        )

    def forget(self) -> None:
        """Borra la licencia de este ordenador (no toca nada más)."""
        with self._lock:
            max_seen = self._data.max_seen
            self._data = StoredLicense(max_seen=max_seen)
            self._save()
        self._notify(force=True)

    # ------------------------------------------------------------------
    def describe(self, status: LicenseStatus | None = None) -> str:
        status = status or self.status()
        if status.state is LicenseState.DISABLED:
            return "Esta versión no necesita licencia."
        if status.state is LicenseState.NONE:
            return status.message
        if status.state is LicenseState.BLOCKED:
            return status.message
        what = "Prueba gratis" if status.is_trial else f"Licencia {status.plan or ''}".strip()
        if status.license_expires_at:
            local = status.license_expires_at.astimezone()
            what += f" activa hasta el {local:%d/%m/%Y a las %H:%M}"
        else:
            what += " activa (sin caducidad)"
        return what + "."

    # ------------------------------------------------------------------
    # Segundo plano
    # ------------------------------------------------------------------
    def _notify(self, *, force: bool = False) -> None:
        status = self.status()
        signature = status.signature()
        if not force and signature == self._last_signature:
            return
        self._last_signature = signature
        for listener in list(self.listeners):
            try:
                listener(status)
            except Exception:  # pragma: no cover - un aviso roto no para nada
                logger.exception("Error en un aviso de licencia")

    def start_background(self, interval: float = 60.0) -> None:
        """Comprueba al abrir y luego cada minuto si toca renovar."""
        if not self.config.enforced or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()

        def loop() -> None:  # pragma: no cover - hilo real (probado en integración)
            first = True
            while not self._stop.is_set():
                try:
                    if first and self._data.key_enc:
                        self.refresh()
                    else:
                        self.refresh_if_due()
                except Exception:
                    logger.exception("Error comprobando la licencia")
                first = False
                self._wake.wait(interval)
                self._wake.clear()

        self._thread = threading.Thread(target=loop, name="lotbot-licencia", daemon=True)
        self._thread.start()

    def check_now(self) -> None:
        """Pide al hilo que compruebe ya (botón «Comprobar ahora»)."""
        with self._lock:
            self._data.next_refresh = 0.0
        self._wake.set()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)
