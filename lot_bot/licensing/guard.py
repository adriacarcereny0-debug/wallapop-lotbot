"""Candado de licencia delante de Wallapop real.

`LicensedService` envuelve el servicio de Wallapop (solo fuera del modo DEMO)
y deja pasar todo lo que es LEER (tus anuncios, mensajes, estadísticas), pero
nada que CAMBIE algo en Wallapop (publicar, editar, borrar, enviar mensajes)
si la licencia no está activa.

Lo que ya se está publicando no se corta: la cola marca su anuncio con
`publication_in_progress()` y ese anuncio termina aunque la licencia caduque
justo a la mitad. La cola, antes de empezar el SIGUIENTE, mira la licencia y
se pausa.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from lot_bot.wallapop.errors import WallapopError

#: Lo que cambia algo en Wallapop.
WRITE_METHODS = frozenset(
    {
        "create_item",
        "update_item",
        "delete_item",
        "update_item_price",
        "update_item_images",
        "upload_image",
        "send_message",
    }
)

_local = threading.local()


@contextmanager
def publication_in_progress() -> Iterator[None]:
    """Durante este bloque, el anuncio que se está publicando termina pase lo que pase."""
    depth = getattr(_local, "depth", 0)
    _local.depth = depth + 1
    try:
        yield
    finally:
        _local.depth = depth


def _in_progress() -> bool:
    return getattr(_local, "depth", 0) > 0


class LicenseRequiredError(WallapopError):
    user_message = (
        "Tu licencia de LOT Bot no está activa: no se puede hacer nada nuevo en Wallapop. "
        "Tus datos siguen aquí. Actívala en Configuración → Licencia (o usa el modo DEMO)."
    )
    retryable = False


class LicensedService:
    """Proxy transparente: mismos atributos que el servicio que envuelve."""

    def __init__(self, inner: Any, allows: Callable[[], bool], reason: Callable[[], str]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_allows", allows)
        object.__setattr__(self, "_reason", reason)

    @property
    def wrapped(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._inner, name)
        if name in WRITE_METHODS and callable(value):
            allows, reason = self._allows, self._reason

            def guarded(*args: Any, **kwargs: Any) -> Any:
                if not _in_progress() and not allows():
                    raise LicenseRequiredError(reason())
                return value(*args, **kwargs)

            guarded.__name__ = name
            return guarded
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)

    def __repr__(self) -> str:  # pragma: no cover
        return f"LicensedService({self._inner!r})"


def guard_backend(backend: Any, manager: Any) -> Any:
    """Pone el candado al backend si es Wallapop real y se exige licencia."""
    if manager is None or backend.demo or not manager.enforced:
        return backend
    if isinstance(backend.service, LicensedService):
        return backend
    backend.service = LicensedService(
        backend.service,
        manager.allows_real_use,
        lambda: manager.describe(),
    )
    return backend
