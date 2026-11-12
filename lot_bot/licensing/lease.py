"""Comprobación local del pase firmado que da el servidor.

Formato: ``LBT1.<base64url(json)>.<base64url(firma)>``. La firma Ed25519 cubre
``LBT1.<base64url(json)>``. El json lleva, entre otros:
``typ`` («lotbot-lease»), ``kh`` (huella de la clave de licencia), ``dev``
(huella del ordenador), ``kind``, ``plan``, ``seats``, ``lic_exp``, ``iat`` y
``exp`` (segundos Unix).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TOKEN_PREFIX = "LBT1"
TOKEN_TYPE = "lotbot-lease"


class LeaseError(Exception):
    """El pase no es válido (firma, formato, otra clave u otro ordenador)."""


def key_hash(license_key: str) -> str:
    """Igual que el servidor: sha256 de la clave normalizada, 16 primeros hex."""
    return hashlib.sha256(license_key.strip().upper().encode("utf-8")).hexdigest()[:16]


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


@dataclass(frozen=True)
class Lease:
    token: str
    license_id: int
    key_hash: str
    device: str
    kind: str
    plan: str | None
    seats: int
    license_expires_at: int | None
    issued_at: int
    expires_at: int
    key_id: str

    @classmethod
    def from_payload(cls, token: str, data: dict[str, Any]) -> Lease:
        try:
            return cls(
                token=token,
                license_id=int(data["lic"]),
                key_hash=str(data["kh"]),
                device=str(data["dev"]),
                kind=str(data.get("kind") or ""),
                plan=(str(data["plan"]) if data.get("plan") else None),
                seats=int(data.get("seats") or 1),
                license_expires_at=(int(data["lic_exp"]) if data.get("lic_exp") else None),
                issued_at=int(data["iat"]),
                expires_at=int(data["exp"]),
                key_id=str(data.get("kid") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LeaseError("Al pase le faltan datos.") from exc


def verify_lease(
    token: str,
    public_keys: tuple[bytes, ...],
    *,
    license_key: str,
    fingerprint: str,
) -> Lease:
    """Comprueba firma, tipo, clave y ordenador. NO mira la fecha (eso lo
    decide el gestor, que sabe qué hora es de verdad)."""
    if not public_keys:
        raise LeaseError("No hay clave pública para comprobar el pase.")
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LeaseError("El pase no tiene el formato esperado.")
    signed = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        signature = _b64url_decode(parts[2])
        body = _b64url_decode(parts[1])
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise LeaseError("El pase está dañado.") from exc

    for raw in public_keys:
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(signature, signed)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        raise LeaseError("La firma del pase no es válida.")

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeaseError("El pase está dañado.") from exc
    if not isinstance(data, dict) or data.get("typ") != TOKEN_TYPE or data.get("v") != 1:
        raise LeaseError("El pase no es de LOT Bot.")
    lease = Lease.from_payload(token, data)
    if lease.key_hash != key_hash(license_key):
        raise LeaseError("El pase es de otra clave de licencia.")
    if lease.device != fingerprint:
        raise LeaseError("El pase es de otro ordenador.")
    return lease
