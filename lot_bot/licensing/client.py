"""Llamadas al servidor de licencias (API v1 de la web)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from lot_bot import __version__
from lot_bot.licensing.fingerprint import DeviceInfo

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)

#: Respuestas que cambian el estado de la licencia. Cualquier otra cosa
#: (sin red, error 5xx, demasiadas peticiones...) es pasajera: se sigue con
#: el pase que haya y se vuelve a probar más tarde.
DEFINITIVE_CODES = frozenset(
    {
        "LICENSE_NOT_FOUND",
        "LICENSE_EXPIRED",
        "LICENSE_SUSPENDED",
        "LICENSE_REVOKED",
        "DEVICE_BLOCKED",
        "DEVICE_NOT_ACTIVATED",
        "DEVICE_LIMIT",
        "TRIAL_ALREADY_USED",
        "TOO_MANY_CHANGES",
        "INVALID_REQUEST",
    }
)


class TransientError(Exception):
    """No se ha podido hablar con el servidor (o no ha contestado bien)."""


@dataclass
class ServerReply:
    ok: bool
    code: str = ""
    message: str = ""
    token: str | None = None
    server_time: str | None = None
    license: dict[str, Any] = field(default_factory=dict)


class LicenseClient:
    def __init__(self, server: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self.server = server.rstrip("/")
        self._transport = transport

    def _post(self, path: str, body: dict[str, Any], *, expect_token: bool = True) -> ServerReply:
        url = f"{self.server}/api/v1/license/{path}"
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport) as client:
                response = client.post(
                    url, json=body, headers={"User-Agent": f"LOT-Bot/{__version__}"}
                )
        except httpx.HTTPError as exc:
            raise TransientError(f"Sin conexión con el servidor de licencias ({type(exc).__name__}).") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise TransientError(f"Respuesta no válida del servidor ({response.status_code}).") from exc
        if not isinstance(data, dict):
            raise TransientError(f"Respuesta no válida del servidor ({response.status_code}).")
        if data.get("ok") is True and response.status_code == 200:
            if not expect_token:
                return ServerReply(ok=True)
            token = data.get("token")
            if not isinstance(token, str) or not token:
                raise TransientError("El servidor no ha devuelto el pase.")
            return ServerReply(
                ok=True,
                token=token,
                server_time=data.get("server_time"),
                license=data.get("license") or {},
            )
        code = str(data.get("code") or "")
        if code in DEFINITIVE_CODES and 400 <= response.status_code < 500:
            return ServerReply(
                ok=False,
                code=code,
                message=str(data.get("message") or ""),
                license=data.get("license") or {},
            )
        raise TransientError(
            f"El servidor de licencias no está disponible ({response.status_code} {code})."
        )

    @staticmethod
    def _device(device: DeviceInfo) -> dict[str, str]:
        return {
            "fingerprint": device.fingerprint,
            "name": device.name,
            "os": device.os,
            "app_version": __version__,
        }

    def activate(self, key: str, device: DeviceInfo) -> ServerReply:
        return self._post("activate", {"key": key, "device": self._device(device)})

    def refresh(self, key: str, device: DeviceInfo) -> ServerReply:
        return self._post("refresh", {"key": key, "device": self._device(device)})

    def deactivate(self, key: str, device: DeviceInfo) -> ServerReply:
        return self._post(
            "deactivate", {"key": key, "device": self._device(device)}, expect_token=False
        )
