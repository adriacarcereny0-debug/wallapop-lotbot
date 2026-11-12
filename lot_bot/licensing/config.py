"""Dónde está el servidor de licencias y con qué clave pública se comprueban los pases.

La clave PÚBLICA va dentro del programa. Mientras esté vacía, LOT Bot no exige
licencia (funciona como siempre): así se puede publicar esta versión antes de
tener el servidor listo sin dejar a nadie sin programa.

Para activar las licencias se pega aquí la clave pública que da
`node web/scripts/generar-claves.mjs` (la PRIVADA va solo en Vercel).
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass

from lot_bot.config.paths import is_frozen

#: Claves públicas Ed25519 (32 bytes en base64) que firman los pases. Se admite
#: más de una para poder cambiar de clave sin dejar a nadie fuera.
EMBEDDED_PUBLIC_KEYS: tuple[str, ...] = ()

DEFAULT_SERVER = "https://www.lotbot.es"
PURCHASE_URL = "https://www.lotbot.es/#precios"

ENV_SERVER = "LOT_BOT_LICENSE_SERVER"
ENV_PUBLIC_KEY = "LOT_BOT_LICENSE_PUBLIC_KEY"


def decode_public_key(value: str) -> bytes | None:
    """32 bytes de la clave pública, o None si el texto no es una clave válida."""
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


@dataclass(frozen=True)
class LicenseConfig:
    server: str
    public_keys: tuple[bytes, ...]

    @property
    def enforced(self) -> bool:
        """¿Se exige licencia para usar Wallapop real?"""
        return bool(self.public_keys and self.server)


def load_config() -> LicenseConfig:
    """Configuración efectiva.

    En el programa instalado (ejecutable) solo valen las claves de dentro del
    programa: una variable de entorno no puede cambiar quién firma los pases.
    Desde el código fuente se puede apuntar a un servidor de pruebas.
    """
    keys = [decode_public_key(k) for k in EMBEDDED_PUBLIC_KEYS]
    server = DEFAULT_SERVER
    if not is_frozen():
        override = os.environ.get(ENV_PUBLIC_KEY, "").strip()
        if override:
            keys = [decode_public_key(k) for k in override.split(",")]
        server = os.environ.get(ENV_SERVER, "").strip() or server
    return LicenseConfig(server=server.rstrip("/"), public_keys=tuple(k for k in keys if k))
