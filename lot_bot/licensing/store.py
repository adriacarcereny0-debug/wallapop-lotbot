"""Lo que LOT Bot recuerda de la licencia en este ordenador.

Fichero ``config/licencia.json`` dentro de la carpeta de datos (fuera del
programa: no se pierde al actualizar). La clave de licencia va cifrada con la
misma caja que las demás claves locales; el pase no hace falta cifrarlo
porque está firmado (cambiarlo lo invalida).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FILENAME = "licencia.json"


@dataclass
class StoredLicense:
    key_enc: str | None = None
    token: str | None = None
    #: La hora más alta vista (para notar si alguien atrasa el reloj).
    max_seen: float = 0.0
    #: Diferencia entre la hora del servidor y la del ordenador (segundos).
    clock_offset: float = 0.0
    last_success: float = 0.0
    last_attempt: float = 0.0
    next_refresh: float = 0.0
    #: Último intento falló por la red (sin conexión): se sigue con el pase.
    offline: bool = False
    #: Respuesta definitiva del servidor (caducada, suspendida, revocada...).
    blocked_code: str | None = None
    blocked_message: str | None = None
    #: Lo último que dijo el servidor de la licencia (para mostrarlo).
    info: dict[str, Any] = field(default_factory=dict)


class LicenseStore:
    def __init__(self, folder: Path) -> None:
        self.path = Path(folder) / FILENAME
        self._lock = threading.Lock()

    def load(self) -> StoredLicense:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return StoredLicense()
            except (OSError, ValueError):
                logger.warning("El fichero de licencia está dañado: se empieza de cero.")
                return StoredLicense()
            known = {f.name for f in fields(StoredLicense)}
            data = {k: v for k, v in (raw or {}).items() if k in known}
            try:
                return StoredLicense(**data)
            except TypeError:
                return StoredLicense()

    def save(self, data: StoredLicense) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(data), ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:  # pragma: no cover - Windows
                pass
