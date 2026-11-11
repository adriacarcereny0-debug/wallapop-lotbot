"""Cola de publicación automática con intervalo mínimo entre anuncios.

«Publica 10 canapés» crea una cola:

    anuncio 1 → (imagen) → publicar → esperar ≥ intervalo → anuncio 2 → ...

REGLAS
------
* El intervalo mínimo (`minimum_publish_interval_seconds`) es de 60 segundos
  y NO se admiten valores inferiores. Es un mínimo, no un objetivo: si generar
  la imagen tarda más, se espera más.
* El intervalo se cuenta entre CUALQUIER par de publicaciones (también entre
  cuentas distintas) y también entre intentos fallidos.
* Si una publicación falla: se registra el error, el anuncio queda marcado
  y la cola sigue. De serie NO se reintenta solo (`automatic_retries` = 0);
  si se activa (máximo 3), cada reintento respeta el intervalo (el doble, el
  cuádruple...). Si la sesión ha caducado o Wallapop limita las
  peticiones, la cola se PAUSA y espera al usuario: nunca se intenta saltar
  un bloqueo.
* Si Wallapop pide una verificación (CAPTCHA), LOT Bot NUNCA la resuelve: pone
  la ventana de esa cuenta delante, avisa, y la PERSONA la completa. En
  cuanto desaparece, se sigue solo (sin pulsar «Continuar») y desde el mismo
  paso. Se espera lo que haga falta (sin límite de tiempo). Mientras tanto,
  si hay anuncios de OTRAS cuentas, se siguen publicando; el de la cuenta con
  verificación se hace después (solo si aún no se había pulsado «Publicar»).
* Tres fallos seguidos pausan la cola.

RITMO POR CUENTA (para que Wallapop pida menos verificaciones)
--------------------------------------------------------------
Además del intervalo entre CUALQUIER par de anuncios, cada cuenta va a su
propio ritmo, como un vendedor normal (sin trucos para ocultar el bot):

* Entre dos anuncios de la MISMA cuenta pasan al menos
  `account_interval_seconds` (5 min por defecto). Con varias cuentas se van
  alternando, así que en total se publica igual de rápido.
* Tras `batch_size` anuncios seguidos en una cuenta, esa cuenta descansa
  `batch_rest_minutes`; las demás siguen.
* Si Wallapop pide una verificación en una cuenta, durante `slowdown_hours`
  esa cuenta espera el doble entre anuncios.
* «Tus productos» se lee al EMPEZAR la cola (para el máximo de anuncios) y los
  anuncios sin confirmar se comprueban al TERMINAR: nada de lecturas extra
  entre anuncio y anuncio (salvo que fallen varios seguidos).

PRUEBAS
-------
El reloj se puede sustituir (`clock=`) para que las pruebas no esperen 60
segundos de verdad. Solo se admite con el servicio simulado (DEMO): con
Wallapop real se usa siempre el reloj real.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from lot_bot.core.audit import AuditService
from lot_bot.database.engine import Database
from lot_bot.database.models import (
    PublishJob,
    PublishJobStatus,
    PublishTask,
    PublishTaskStatus,
    Setting,
)

logger = logging.getLogger(__name__)

MINIMUM_PUBLISH_INTERVAL_SECONDS = 60
SETTINGS_KEY = "publicacion"
#: Fotos ya publicadas (para no repetirlas nunca, en ninguna cuenta).
USED_PHOTOS_KEY = "fotos_usadas"
#: Marca de que «no repetir fotos» ya se aplicó como opción de serie.
NO_REPEAT_MIGRATION_KEY = "no_repetir_fotos_v2"
NO_PHOTOS_MESSAGE = (
    "Añade fotos nuevas: ya se han publicado todas las fotos marcadas del Anuncio "
    "principal y no se repite ninguna. Añádelas en «Anuncio principal» → «Fotografías…» "
    "(márcalas con «Usar / no usar al publicar») y pulsa «Reanudar»."
)
DEFAULT_PUBLISH_SETTINGS: dict[str, Any] = {
    "minimum_publish_interval_seconds": MINIMUM_PUBLISH_INTERVAL_SECONDS,
    # Las imágenes ya no se generan con IA (solo fotos subidas por el usuario).
    "generate_images": False,
    # No repetir fotos (la opción segura, activada de serie): una foto
    # distinta en cada anuncio y nunca una ya publicada. False = todas las
    # marcadas en cada anuncio.
    "rotate_photos": True,
    "automatic_retries": 0,  # «una vez» es una vez: sin reintentos automáticos
    # Máximo de anuncios por cuenta (0 = sin límite). Al llegar, se eliminan
    # los MÁS ANTIGUOS para dejar sitio al nuevo.
    "max_listings_per_account": 0,
    # Ritmo por cuenta (ver RITMO POR CUENTA).
    "account_interval_seconds": 300,
    "batch_size": 10,  # 0 = sin descansos
    "batch_rest_minutes": 20,
    "slowdown_hours": 3,  # 0 = no ir más despacio tras una verificación
    # Varias cuentas A LA VEZ: cada cuenta con su propia cola y su navegador
    # (False = por turnos, de uno en uno, como siempre).
    "parallel_accounts": False,
    "max_parallel_accounts": 5,
}
#: Valores admitidos (mínimo, máximo) de los ajustes de ritmo.
PACING_LIMITS: dict[str, tuple[int, int]] = {
    "account_interval_seconds": (MINIMUM_PUBLISH_INTERVAL_SECONDS, 7200),
    "batch_size": (0, 500),
    "batch_rest_minutes": (0, 600),
    "slowdown_hours": (0, 48),
    "max_parallel_accounts": (1, 10),
}
#: Tras una verificación, la cuenta espera este múltiplo de su intervalo.
SLOWDOWN_FACTOR = 2


def _clamp_pacing(values: dict[str, Any]) -> dict[str, Any]:
    for key, (low, high) in PACING_LIMITS.items():
        try:
            number = int(values.get(key, DEFAULT_PUBLISH_SETTINGS[key]))
        except (TypeError, ValueError):
            number = int(DEFAULT_PUBLISH_SETTINGS[key])
        values[key] = max(low, min(high, number))
    return values

#: Solo lo que tiene que hacer una PERSONA pausa la cola y pide «Continuar»
#: (verificación, iniciar sesión, cerrar Chrome, claves...). Nunca se salta.
PAUSING_ERRORS = {
    "VerificationRequiredError",
    "AuthenticationError",
    "AuthorizationError",
    "RateLimitError",
    "NotAvailableWithCurrentAccessError",
    "ConfigurationError",
    "NO_API_KEY",
    "INVALID_KEY",
    "NO_CREDITS",
    "ProfileInUseError",
    "BrowserUnavailable",
    "PublishCancelledError",
}
#: Fallos de UN anuncio (un paso del formulario, un dato, sin confirmación):
#: ese anuncio queda marcado y la cola SIGUE sola con el siguiente.
SKIPPING_ERRORS = {
    "FormMismatchError",
    "ImageUploadError",
    "BrowserStepError",
    "RESULTADO_NO_CONFIRMADO",
    # Se cerró la ventana de una cuenta: ese anuncio no se repite, pero la
    # cadena sigue (para el siguiente se abre otra ventana).
    "WindowClosedError",
}
#: Errores que no se arreglan reintentando.
NON_RETRYABLE = {
    "CALIDAD_INSUFICIENTE",
    "DUPLICATE",
    "RESULTADO_NO_CONFIRMADO",
    "WindowClosedError",
    "PublishCancelledError",
}
UNCONFIRMED_CODE = "RESULTADO_NO_CONFIRMADO"
INTERRUPTED_MESSAGE = (
    "LOT Bot se cerró mientras publicaba este anuncio: puede que llegara a publicarse. "
    "Se buscará en «Tus productos» al terminar la cola; revísalo en Wallapop antes de "
    "reintentarlo."
)
RELOGIN_CODE = "INICIAR_SESION"
#: Anuncio que espera a que la persona complete una verificación de Wallapop.
VERIFICATION_CODE = "VERIFICACION"
DEFERRED_CODE = "VerificationDeferredError"
#: Máximo que se espera a la persona (verificación, iniciar sesión...).
#: None = sin límite: la cola nunca da el anuncio por fallido por tardar.
USER_GATE_TIMEOUT_S: float | None = None
#: Cada cuánto se mira si la persona ya ha completado la verificación.
VERIFICATION_POLL_S = 3.0
#: Respuesta de `_user_gate` para «haz este anuncio después» (la de form.DEFER).
GATE_DEFER = "aplazar"
VERIFICATION_WAIT_MESSAGE = (
    "Wallapop pide una verificación. Complétala en la ventana de Chrome de esta "
    "cuenta (se ha puesto delante). En cuanto desaparezca, LOT Bot sigue solo: no "
    "hace falta pulsar «Continuar»."
)
VERIFICATION_TASK_MESSAGE = (
    "Esperando a que completes la verificación de Wallapop en la ventana de esta "
    "cuenta. Mientras tanto se publica en las demás; este anuncio se hace después."
)
#: Seguridad: si fallan tantos anuncios SEGUIDOS, algo ha cambiado en la web
#: y no tiene sentido seguir gastando intentos: se pausa y se avisa.
MAX_CONSECUTIVE_FAILURES = 3
#: Cola «a la vez»: separación mínima entre los ARRANQUES de publicaciones de
#: cuentas distintas (no se abren todas en el mismo segundo).
PARALLEL_START_GAP_S = 15
#: Fotos que Wallapop ha rechazado (no se vuelven a elegir).
REJECTED_PHOTOS_KEY = "fotos_rechazadas"
#: Anuncios ya existentes por cuenta al empezar cada cola (para reconocer
#: después, sin dudas, cuáles son nuevos).
KNOWN_LISTINGS_KEY = "cola_{job}_conocidos"
MISSING_PHOTOS_MESSAGE = (
    "Faltan {n} foto(s) marcada(s) del Anuncio principal: {names}. Se borraron o se "
    "movieron del ordenador, o están dañadas. NO se publica con menos fotos sin "
    "avisarte: vuelve a añadirlas en «Anuncio principal» → «Fotografías…», o pulsa "
    "«Continuar» para publicar esta cola con las {left} que quedan."
)


def validate_interval(seconds: Any) -> int:
    try:
        value = int(seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("El intervalo debe ser un número de segundos.") from exc
    if value < MINIMUM_PUBLISH_INTERVAL_SECONDS:
        raise ValueError(
            f"El intervalo mínimo entre publicaciones no puede ser inferior a "
            f"{MINIMUM_PUBLISH_INTERVAL_SECONDS} segundos."
        )
    return value


# ---------------------------------------------------------------------------
# Reloj
# ---------------------------------------------------------------------------
class Clock:
    """Reloj real. `sleep` se interrumpe si se pide parar."""

    is_real = True

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float, interrupt: threading.Event) -> None:
        interrupt.wait(max(0.0, seconds))


class FakeClock(Clock):
    """Reloj simulado para pruebas: dormir solo avanza el tiempo."""

    is_real = False

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.t = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float, interrupt: threading.Event) -> None:
        seconds = max(0.0, seconds)
        self.slept.append(seconds)
        self.t += seconds


# ---------------------------------------------------------------------------
@dataclass(slots=True)
class QueueProgress:
    job_id: int
    name: str
    status: str
    total: int
    published: int
    failed: int
    pending: int
    in_progress: int
    cancelled: int
    interval_seconds: int
    current_account: str | None
    last_publish_at: datetime | None
    next_allowed_at: datetime | None
    pause_reason: str | None
    is_demo: bool
    tasks: list[dict[str, Any]] = field(default_factory=list)
    #: Varias cuentas a la vez (cada una con su cola y su navegador).
    parallel: bool = False
    #: Cuentas publicando ahora mismo (colas «a la vez»).
    publishing_accounts: list[str] = field(default_factory=list)

    @property
    def done(self) -> int:
        return self.published + self.failed + self.cancelled

    def bar(self, width: int = 10) -> str:
        filled = int(round(width * self.published / self.total)) if self.total else 0
        return "█" * filled + "░" * (width - filled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cola": self.job_id,
            "nombre": self.name,
            "estado": self.status,
            "total": self.total,
            "publicados": self.published,
            "fallidos": self.failed,
            "pendientes": self.pending,
            "en_curso": self.in_progress,
            "cancelados": self.cancelled,
            "intervalo_segundos": self.interval_seconds,
            "cuenta_actual": self.current_account,
            "ultima_publicacion": self.last_publish_at.strftime("%H:%M:%S")
            if self.last_publish_at
            else None,
            "proxima_permitida": self.next_allowed_at.strftime("%H:%M:%S")
            if self.next_allowed_at
            else None,
            "motivo_pausa": self.pause_reason,
            "demo": self.is_demo,
            "a_la_vez": self.parallel,
        }


class PublishQueue:
    """Ejecuta las colas de publicación, de una en una y en segundo plano."""

    def __init__(
        self,
        database: Database,
        audit: AuditService,
        app: Any,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._db = database
        self._audit = audit
        self._app = app
        self.clock = clock or Clock()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_attempt: float | None = None
        self._consecutive_failures = 0
        #: Avisos para la interfaz (se llaman desde el hilo de la cola).
        self.listeners: list[Callable[[int], None]] = []
        #: Cuentas en las que Wallapop pide una verificación ahora mismo:
        #: {cuenta: {"cola", "desde", "aplazada"}}. «aplazada» = su anuncio
        #: se hará después y mientras tanto se publica en otras cuentas.
        self._verifying: dict[str, dict[str, Any]] = {}
        self._verifying_lock = threading.Lock()
        self._last_verification_poll = 0.0
        #: Cuentas cuya ventana hay que volver a poner delante (botón del aviso).
        self._focus_requests: set[str] = set()
        #: Ritmo por cuenta (reloj de la cola): último intento, anuncios
        #: seguidos, descanso hasta y «más despacio» hasta.
        self._account_last: dict[str, float] = {}
        self._account_streak: dict[str, int] = {}
        self._account_rest_until: dict[str, float] = {}
        self._account_slow_until: dict[str, float] = {}
        #: Cola «a la vez»: un hilo por cuenta.
        self._lanes: dict[str, threading.Thread] = {}
        self._lanes_lock = threading.Lock()
        self._last_parallel_start: float | None = None
        #: Estado compartido entre hilos (fotos usadas, anuncios conocidos...).
        self._state_lock = threading.RLock()
        #: Fotos elegidas para un anuncio que aún se está publicando: ninguna
        #: otra cuenta puede elegirlas a la vez. {foto: id del anuncio}.
        self._reserved_photos: dict[str, int] = {}
        #: Colas en las que la persona ya ha aceptado publicar con las fotos que quedan.
        self._accepted_missing: set[int] = set()
        self._missing_warned: dict[int, list[str]] = {}
        self._photo_warned: set[tuple[int, str]] = set()

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        with self._db.session_scope() as session:
            row = session.get(Setting, SETTINGS_KEY)
            values = {**DEFAULT_PUBLISH_SETTINGS, **((row.value or {}) if row else {})}
        # Un valor inferior guardado a mano en la base de datos no se respeta.
        try:
            values["minimum_publish_interval_seconds"] = validate_interval(
                values["minimum_publish_interval_seconds"]
            )
        except ValueError:
            values["minimum_publish_interval_seconds"] = MINIMUM_PUBLISH_INTERVAL_SECONDS
        # Generar imágenes con IA está retirado: aunque una configuración
        # antigua lo tenga activado, se publican siempre las fotos propias.
        values["generate_images"] = False
        # «No repetir fotos» pasa a ser la opción de serie. Una configuración
        # guardada antes de este cambio (donde «no» era lo de serie) se activa
        # una vez; si después alguien lo apaga a propósito, se respeta.
        if not values.get(NO_REPEAT_MIGRATION_KEY):
            values["rotate_photos"] = True
        # Un valor raro guardado a mano no debe tumbar la cola al fallar un anuncio.
        try:
            values["automatic_retries"] = max(0, min(3, int(values.get("automatic_retries") or 0)))
        except (TypeError, ValueError):
            values["automatic_retries"] = 0
        return _clamp_pacing(values)

    def save_settings(self, **changes: Any) -> dict[str, Any]:
        if "minimum_publish_interval_seconds" in changes:
            changes["minimum_publish_interval_seconds"] = validate_interval(
                changes["minimum_publish_interval_seconds"]
            )
        if "automatic_retries" in changes:
            changes["automatic_retries"] = max(0, min(3, int(changes["automatic_retries"])))
        merged = _clamp_pacing({**self.settings(), **changes})
        merged["generate_images"] = False  # imágenes con IA: retirado
        merged[NO_REPEAT_MIGRATION_KEY] = True
        with self._db.session_scope() as session:
            row = session.get(Setting, SETTINGS_KEY)
            if row is None:
                session.add(Setting(key=SETTINGS_KEY, value=merged))
            else:
                row.value = merged
        self._audit.record_success(
            "Configuración de la cola de publicación",
            detail=f"Intervalo mínimo: {merged['minimum_publish_interval_seconds']} s",
            actor="usuario",
        )
        return merged

    @property
    def interval(self) -> int:
        return self.settings()["minimum_publish_interval_seconds"]

    def _check_clock(self) -> None:
        """La aceleración de pruebas nunca puede llegar a Wallapop real."""
        if not self.clock.is_real and not getattr(self._app.wallapop, "is_mock", False):
            raise RuntimeError(
                "El reloj de pruebas solo se admite en modo DEMO: con Wallapop real se "
                "respeta siempre el intervalo real."
            )

    # ------------------------------------------------------------------
    # Crear colas
    # ------------------------------------------------------------------
    def enqueue_master(
        self,
        key: str | None,
        account_refs: list[str],
        copies: int | None,
        overrides: dict[str, Any] | None = None,
        *,
        generate_images: bool | None = None,
        actor: str = "usuario",
        start: bool = True,
        parallel: bool | None = None,
    ) -> int:
        """Crea una cola con copias del anuncio principal. Devuelve su id.

        `parallel`: publicar en las cuentas A LA VEZ (cada una con su propia
        cola y su navegador). None = lo que diga la configuración."""
        master = self._app.master_ads.get(key)
        if master is None:
            raise ValueError("No existe el anuncio principal.")
        if not self._app.demo_mode:
            accounts = {a.internal_ref: a for a in self._app.accounts.list_accounts()}
            demo_only = [
                accounts[r].alias for r in account_refs if r in accounts and accounts[r].is_demo
            ]
            if demo_only:
                raise ValueError(
                    "Estas cuentas son solo de demostración y no pueden publicar en Wallapop: "
                    + ", ".join(demo_only)
                )
        refs = self._app.master_ads.distribute(account_refs, copies)
        if not refs:
            raise ValueError("No hay cuentas en las que publicar.")
        settings = self.settings()
        if generate_images is None:
            generate_images = bool(settings["generate_images"])
        rendered = self._app.master_ads.render(master, overrides)
        title = rendered["title"]
        if parallel is None:
            parallel = bool(settings.get("parallel_accounts"))
        # Con una sola cuenta no hay nada que hacer a la vez.
        parallel = bool(parallel) and len(set(refs)) > 1
        with self._db.session_scope() as session:
            job = PublishJob(
                name=f"{len(refs)} × {master.name}",
                status=PublishJobStatus.PENDING,
                interval_seconds=settings["minimum_publish_interval_seconds"],
                generate_images=generate_images,
                is_demo=bool(self._app.demo_mode),
                parallel=parallel,
                actor=actor,
            )
            session.add(job)
            session.flush()
            for position, ref in enumerate(refs, start=1):
                session.add(
                    PublishTask(
                        job_id=job.id,
                        position=position,
                        account_ref=ref,
                        title=title[:200],
                        payload={
                            "master_key": master.key,
                            "overrides": dict(overrides or {}),
                            # Lo que se espera ver en Wallapop (para reconocerlo
                            # si no confirma): título y precio.
                            "precio": rendered.get("price"),
                        },
                    )
                )
            job_id = job.id
        self._audit.record_success(
            "Cola de publicación creada",
            target=master.name,
            detail=f"{len(refs)} anuncio(s), intervalo mínimo "
            f"{settings['minimum_publish_interval_seconds']} s"
            + (", una imagen generada por anuncio" if generate_images else "")
            + (", varias cuentas a la vez" if parallel else ""),
            actor=actor,
        )
        if start:
            self.start(job_id)
        return job_id

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def _set_job(self, job_id: int, status: PublishJobStatus, reason: str | None = None) -> None:
        with self._db.session_scope() as session:
            job = session.get(PublishJob, job_id)
            if job is None:
                raise ValueError(f"No existe la cola {job_id}.")
            job.status = status
            job.pause_reason = reason
            if status is PublishJobStatus.RUNNING and job.started_at is None:
                job.started_at = datetime.now()
            if status in (PublishJobStatus.COMPLETED, PublishJobStatus.CANCELLED):
                job.finished_at = datetime.now()
        self._notify(job_id)

    def start(self, job_id: int) -> None:
        self._set_job(job_id, PublishJobStatus.RUNNING)
        self._audit.record_success("Cola de publicación iniciada", detail=f"Cola {job_id}")
        self._wake.set()

    def pause(self, job_id: int, reason: str = "Pausada por el usuario.") -> None:
        self._set_job(job_id, PublishJobStatus.PAUSED, reason)
        self._audit.record_success("Cola de publicación pausada", detail=f"Cola {job_id}: {reason}")

    def resume(self, job_id: int) -> None:
        self._consecutive_failures = 0
        if job_id in self._missing_warned:
            # «Continuar» tras el aviso de fotos que faltan: se publica con las que quedan.
            self._accepted_missing.add(job_id)
            self._audit.record_success(
                "Publicar con las fotos que quedan (aceptado)",
                detail=f"Cola {job_id}: faltan " + ", ".join(self._missing_warned[job_id]),
                actor="usuario",
            )
        self._set_job(job_id, PublishJobStatus.RUNNING)
        self._audit.record_success("Cola de publicación reanudada", detail=f"Cola {job_id}")
        self._wake.set()

    def cancel(self, job_id: int) -> int:
        """Cancela lo que queda por publicar. Lo publicado no se toca."""
        with self._db.session_scope() as session:
            tasks = session.scalars(
                select(PublishTask).where(
                    PublishTask.job_id == job_id,
                    PublishTask.status.in_(
                        [
                            PublishTaskStatus.PENDING,
                            PublishTaskStatus.WAITING,
                            PublishTaskStatus.GENERATING,
                        ]
                    ),
                )
            ).all()
            for task in tasks:
                task.status = PublishTaskStatus.CANCELLED
            count = len(tasks)
        with self._verifying_lock:
            for ref in [r for r, v in self._verifying.items() if v["cola"] == job_id]:
                del self._verifying[ref]
        self._set_job(job_id, PublishJobStatus.CANCELLED, "Cancelada por el usuario.")
        self._audit.record_cancelled(
            "Cola de publicación cancelada", detail=f"Cola {job_id}: {count} sin publicar"
        )
        return count

    def retry_task(self, task_id: int, *, allow_unconfirmed: bool = False) -> None:
        """Vuelve a poner en la cola un anuncio fallido.

        Uno «sin confirmar» (pudo publicarse) solo si la persona lo pide tras
        revisarlo en Wallapop (`allow_unconfirmed`): nunca de forma automática."""
        allowed = {PublishTaskStatus.FAILED}
        if allow_unconfirmed:
            allowed.add(PublishTaskStatus.UNCONFIRMED)
        with self._db.session_scope() as session:
            task = session.get(PublishTask, task_id)
            if task is None:
                raise ValueError(f"No existe el anuncio {task_id} de la cola.")
            if task.status not in allowed:
                raise ValueError("Solo se pueden reintentar anuncios fallidos.")
            task.status = PublishTaskStatus.PENDING
            task.error = None
            task.error_code = None
            task.attempts = 0
            job_id = task.job_id
        self._consecutive_failures = 0
        self._audit.record_success("Reintento de publicación", detail=f"Anuncio {task_id}")
        self.resume(job_id)

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._db.session_scope() as session:
            rows = session.scalars(
                select(PublishJob).order_by(PublishJob.id.desc()).limit(limit)
            ).all()
            return [{"id": j.id, "nombre": j.name, "estado": j.status.value} for j in rows]

    def published_listing_ids(self, job_id: int) -> list[int]:
        """Anuncios locales creados por esta cola (para «este anuncio»)."""
        from lot_bot.database.models import Account, Listing

        with self._db.session_scope() as session:
            pairs = session.execute(
                select(PublishTask.account_ref, PublishTask.remote_id).where(
                    PublishTask.job_id == job_id,
                    PublishTask.status == PublishTaskStatus.PUBLISHED,
                    PublishTask.remote_id.is_not(None),
                )
            ).all()
            ids: list[int] = []
            for ref, remote_id in pairs:
                listing_id = session.scalar(
                    select(Listing.id)
                    .join(Account, Listing.account_id == Account.id)
                    .where(Account.internal_ref == ref, Listing.wallapop_item_id == remote_id)
                )
                if listing_id is not None:
                    ids.append(listing_id)
            return ids

    def latest_job_id(self) -> int | None:
        with self._db.session_scope() as session:
            return session.scalar(select(func.max(PublishJob.id)))

    def _last_publish_ts(self) -> float | None:
        """Último intento de publicación (en memoria o en la base de datos)."""
        if self._last_attempt is not None:
            return self._last_attempt
        with self._db.session_scope() as session:
            last = session.scalar(select(func.max(PublishTask.started_at)))
        if last is None:
            return None
        # Solo cuenta para el reloj real: las fechas guardadas son reales.
        return last.timestamp() if self.clock.is_real else None

    def next_allowed_ts(self, job_interval: int | None = None, attempts: int = 0) -> float:
        interval = max(job_interval or self.interval, MINIMUM_PUBLISH_INTERVAL_SECONDS)
        if attempts > 0:
            interval *= 2 ** min(attempts, 3)
        last = self._last_publish_ts()
        return self.clock.now() if last is None else max(self.clock.now(), last + interval)

    def progress(self, job_id: int | None = None) -> QueueProgress | None:
        job_id = job_id or self.latest_job_id()
        if job_id is None:
            return None
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        with self._db.session_scope() as session:
            job = session.get(PublishJob, job_id)
            if job is None:
                return None
            tasks = list(job.tasks)
            counts = {status: 0 for status in PublishTaskStatus}
            for task in tasks:
                counts[task.status] += 1
            current = next(
                (
                    t
                    for t in tasks
                    if t.status
                    in (
                        PublishTaskStatus.GENERATING,
                        PublishTaskStatus.WAITING,
                        PublishTaskStatus.PUBLISHING,
                    )
                ),
                None,
            ) or next((t for t in tasks if t.status is PublishTaskStatus.PENDING), None)
            counts_unconfirmed = counts[PublishTaskStatus.UNCONFIRMED]
            published_times = [t.published_at for t in tasks if t.published_at]
            last_attempt = self._last_publish_ts()
            next_allowed = None
            if job.status is PublishJobStatus.RUNNING and last_attempt is not None:
                ts = last_attempt + job.interval_seconds
                if current is not None:
                    ts = max(ts, self.account_ready_ts(current.account_ref))
                next_allowed = datetime.fromtimestamp(ts)
            return QueueProgress(
                job_id=job.id,
                name=job.name,
                status=job.status.value,
                total=len(tasks),
                published=counts[PublishTaskStatus.PUBLISHED],
                failed=counts[PublishTaskStatus.FAILED] + counts_unconfirmed,
                pending=counts[PublishTaskStatus.PENDING],
                in_progress=counts[PublishTaskStatus.GENERATING]
                + counts[PublishTaskStatus.WAITING]
                + counts[PublishTaskStatus.PUBLISHING],
                cancelled=counts[PublishTaskStatus.CANCELLED],
                interval_seconds=job.interval_seconds,
                current_account=aliases.get(current.account_ref, current.account_ref)
                if current
                else None,
                last_publish_at=max(published_times) if published_times else None,
                next_allowed_at=next_allowed,
                pause_reason=job.pause_reason,
                is_demo=job.is_demo,
                parallel=bool(job.parallel),
                publishing_accounts=sorted({
                    aliases.get(t.account_ref, t.account_ref)
                    for t in tasks
                    if t.status in (PublishTaskStatus.WAITING, PublishTaskStatus.PUBLISHING,
                                    PublishTaskStatus.GENERATING)
                }),
                tasks=[
                    {
                        "id": t.id,
                        "posicion": t.position,
                        "cuenta": aliases.get(t.account_ref, t.account_ref),
                        "cuenta_ref": t.account_ref,
                        "anuncio": t.title,
                        "estado": t.status.value,
                        "intentos": t.attempts,
                        "inicio": t.started_at,
                        "publicado": t.published_at,
                        "id_wallapop": t.remote_id,
                        "url": t.remote_url,
                        "imagen": t.image_path,
                        "error": t.error,
                        "codigo_error": t.error_code,
                    }
                    for t in tasks
                ],
            )

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------
    def start_worker(self) -> None:
        """Arranca el hilo que procesa las colas (en la aplicación real)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.recover_interrupted()
        self._thread = threading.Thread(target=self._loop, name="lotbot-cola", daemon=True)
        self._thread.start()

    def recover_interrupted(self) -> None:
        """Al arrancar: deja como estaba lo que se cortó al cerrar LOT Bot."""
        # Una cola que estaba «en marcha» al cerrar el programa se deja en
        # pausa: el usuario decide si sigue.
        with self._db.session_scope() as session:
            for job in session.scalars(
                select(PublishJob).where(PublishJob.status == PublishJobStatus.RUNNING)
            ).all():
                job.status = PublishJobStatus.PAUSED
                job.pause_reason = "LOT Bot se cerró con la cola en marcha. Pulsa «Reanudar»."
            for task in session.scalars(
                select(PublishTask).where(
                    PublishTask.status.in_(
                        [
                            PublishTaskStatus.GENERATING,
                            PublishTaskStatus.WAITING,
                            PublishTaskStatus.PUBLISHING,
                        ]
                    )
                )
            ).all():
                if task.status is PublishTaskStatus.PUBLISHING:
                    # Se cerró a mitad de publicarlo: pudo llegar a pulsar
                    # «Publicar». Volver a ponerlo en la cola podría duplicarlo:
                    # queda «sin confirmar» y se busca en «Tus productos» al
                    # terminar la cola (o lo reintenta la persona tras mirarlo).
                    task.status = PublishTaskStatus.UNCONFIRMED
                    task.error = INTERRUPTED_MESSAGE
                    task.error_code = UNCONFIRMED_CODE
                else:
                    task.status = PublishTaskStatus.PENDING

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)
        self.wait_for_lanes(timeout)

    def _loop(self) -> None:  # pragma: no cover - hilo real
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("Error inesperado en la cola de publicación")
                worked = False
            if not worked:
                self._wake.wait(2.0)
                self._wake.clear()

    def is_publishing(self) -> bool:
        """¿Hay una cola en marcha (o esperando a la persona)?"""
        with self._db.session_scope() as session:
            return session.scalar(
                select(func.count(PublishJob.id)).where(
                    PublishJob.status == PublishJobStatus.RUNNING
                )
            ) > 0 or bool(self.verifying_accounts())

    def _active_job(self) -> int | None:
        with self._db.session_scope() as session:
            return session.scalar(
                select(PublishJob.id)
                .where(PublishJob.status == PublishJobStatus.RUNNING)
                .order_by(PublishJob.id)
                .limit(1)
            )

    def _job_status(self, job_id: int) -> PublishJobStatus:
        with self._db.session_scope() as session:
            return session.get(PublishJob, job_id).status

    def run_until_idle(self, max_steps: int = 1000) -> int:
        """Procesa todo lo pendiente sin hilo (pruebas). Devuelve pasos."""
        steps = 0
        while steps < max_steps and self.run_once():
            steps += 1
        return steps

    def run_once(self) -> bool:
        """Procesa el siguiente anuncio de la cola activa. False si no hay nada.

        En una cola «a la vez» (`parallel`) no publica él mismo: arranca un
        hilo por cuenta (cada uno con su propia cola de anuncios y su propio
        navegador) y da la cola por terminada cuando todos han acabado."""
        with self._lock:
            job_id = self._active_job()
            if job_id is None:
                return False
            self._check_clock()
            if self._job_is_parallel(job_id):
                return self._coordinate_parallel(job_id)
            with self._db.session_scope() as session:
                pending = session.scalars(
                    select(PublishTask)
                    .where(
                        PublishTask.job_id == job_id,
                        PublishTask.status == PublishTaskStatus.PENDING,
                    )
                    .order_by(PublishTask.position)
                ).all()
                # Las cuentas no conectadas (p. ej. desconectadas por el usuario)
                # y las que esperan una verificación esperan; las demás siguen.
                verifying = self.verifying_accounts()
                candidates = [
                    t
                    for t in pending
                    if t.account_ref not in verifying and self._account_usable(t.account_ref)
                ]
                task = self._pick_by_pace(candidates)
                waiting = sorted({t.account_ref for t in pending}) if pending and task is None else []
                only_verifying = bool(waiting) and all(r in verifying for r in waiting)
                blocked = [] if only_verifying else [r for r in waiting if r not in verifying]
                job_done = not only_verifying and not blocked and task is None
                task_id = task.id if task is not None else None
            if only_verifying:
                # Solo quedan anuncios de cuentas con verificación: se mira si
                # la persona ya la ha completado (la cola sigue «en marcha»).
                self._poll_verifications(force=True)
                return False
            if blocked:
                self._pause_blocked(job_id, blocked)
                return True
            if job_done:
                self._finish_job(job_id)
                return True
            return self._process_task(job_id, task_id, parallel=False)

    def _pause_blocked(self, job_id: int, blocked: list[str]) -> None:
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        names = ", ".join(aliases.get(r, r) for r in blocked)
        self.pause(
            job_id,
            f"Estas cuentas no están conectadas en LOT Bot: {names}. Conéctalas en "
            "Cuentas; al comprobarse la sesión la cola continúa sola.",
        )

    def _finish_job(self, job_id: int) -> None:
        # Los que Wallapop no confirmó se buscan ahora en «Tus productos» (una
        # lectura por cuenta, al final de la cola).
        self._confirm_unconfirmed(job_id)
        self._set_job(job_id, PublishJobStatus.COMPLETED)
        self._forget_job_state(job_id)
        self._audit.record_success(
            "Cola de publicación terminada", detail=self.progress(job_id).name
        )

    def _process_task(self, job_id: int, task_id: int, *, parallel: bool) -> bool:
        """Publica UN anuncio: esperar su turno → foto → publicar → resultado.

        `parallel`: lo llama el hilo de su cuenta (cola «a la vez»). Entonces
        solo cuenta el ritmo de ESA cuenta (más una separación corta entre
        arranques de cuentas distintas); si no, el intervalo entre cualquier
        par de anuncios, como siempre."""
        with self._db.session_scope() as session:
            job = session.get(PublishJob, job_id)
            task = session.get(PublishTask, task_id)
            if task is None or task.status is not PublishTaskStatus.PENDING:
                return True
            ref, attempts = task.account_ref, task.attempts
            payload = dict(task.payload or {})
            image_path = task.image_path
            generate = job.generate_images
            interval = job.interval_seconds
            actor = job.actor
            position = task.position

        def ready_ts() -> float:
            if parallel:
                return self._lane_ready_ts(ref, interval, attempts)
            return self._ready_ts(ref, interval, attempts)

        # 1. Imagen única para este anuncio.
        if generate and not image_path:
            self._set_task(task_id, status=PublishTaskStatus.GENERATING)
            image_path = self._generate_image(task_id, job_id, position, ref, payload)
            if image_path is None:
                return True

        # 2. Esperar el intervalo mínimo. Mientras tanto se hace sitio (si la
        #    cuenta está al máximo).
        self._set_task(task_id, status=PublishTaskStatus.WAITING)
        service = getattr(self._app, "wallapop", None)
        if service is not None and hasattr(service, "user_gate"):
            service.user_gate = self._user_gate
        self._current_job = job_id
        self._make_room(job_id, ref)
        while True:
            wait = ready_ts() - self.clock.now()
            if wait <= 0 and parallel and not self._take_parallel_start():
                wait = 1.0  # otra cuenta acaba de empezar: separación corta
            if wait <= 0:
                break
            self._poll_verifications()
            self.clock.sleep(min(wait, 1.0), self._stop)
            if self._stop.is_set():
                self._set_task(task_id, status=PublishTaskStatus.PENDING)
                return False
            status = self._job_status(job_id)
            if status is not PublishJobStatus.RUNNING:
                if status is PublishJobStatus.PAUSED:
                    self._set_task(task_id, status=PublishTaskStatus.PENDING)
                elif status is PublishJobStatus.CANCELLED:
                    self._set_task(task_id, status=PublishTaskStatus.CANCELLED)
                return True

        # 3. Fotos: comprobar que están todas (y que no están dañadas).
        only_images = None
        photo_key = None
        master_key = payload.get("master_key")
        if (
            not image_path
            and self.settings().get("rotate_photos")
            and self._has_own_photos(master_key)
        ):
            photo = self._reserve_photo(master_key, task_id, job_id)
            if photo is None:
                # No quedan fotos sin publicar: se para y se avisa.
                self._set_task(task_id, status=PublishTaskStatus.PENDING, attempts=attempts)
                self.pause(job_id, NO_PHOTOS_MESSAGE)
                return True
            only_images = [photo["path"]]
            photo_key = self.photo_key(photo)
        elif not image_path and not self._photos_ok_to_publish(job_id, master_key):
            # Falta alguna foto marcada: NUNCA se publica con menos sin avisar.
            self._set_task(task_id, status=PublishTaskStatus.PENDING, attempts=attempts)
            return True

        # 4. Publicar.
        self._set_task(
            task_id,
            status=PublishTaskStatus.PUBLISHING,
            started_at=datetime.fromtimestamp(self.clock.now()),
            attempts=attempts + 1,
        )
        self._last_attempt = self.clock.now()
        self._account_attempted(ref)
        self._current_job = job_id
        self._remember_known_listings(job_id, ref)
        try:
            outcome = self._app.master_ads.publish_single(
                master_key,
                ref,
                payload.get("overrides") or {},
                extra_images=[image_path] if image_path else None,
                only_images=only_images,
                meta={"imagen": payload.get("imagen") or {"origen": "plantilla"}},
                confirmed=True,
                actor=actor,
            )
        except Exception as exc:  # errores de configuración, capacidad...
            self._release_photo(photo_key)
            code = type(exc).__name__
            message = getattr(exc, "user_message", None) or str(exc)
            if code == DEFERRED_CODE:
                self._defer_task(task_id, attempts)
                return True
            if self._photo_rejected(task_id, job_id, code, photo_key, attempts, message):
                return True
            self._fail(task_id, job_id, attempts + 1, code, message)
            return True

        if not outcome.success and outcome.error_code == DEFERRED_CODE:
            self._release_photo(photo_key)
            self._defer_task(task_id, attempts)
            return True
        if outcome.success:
            self._reset_failures()
            if photo_key:
                self.mark_photo_used(photo_key, ref)
            self._set_task(
                task_id,
                status=PublishTaskStatus.PUBLISHED,
                published_at=datetime.fromtimestamp(self.clock.now()),
                remote_id=outcome.item_id,
                remote_url=outcome.url,
                error=None,
                error_code=None,
            )
        elif outcome.error_code == UNCONFIRMED_CODE and self._unconfirmed_found_now(
            task_id, job_id, ref, outcome.message, photo_key
        ):
            # Wallapop no lo confirmó en pantalla, pero está en «Tus productos».
            self._reset_failures()
        elif outcome.error_code == UNCONFIRMED_CODE:
            self._release_photo(photo_key, used=True)  # ya marcada: pudo publicarse
            self._fail(task_id, job_id, attempts + 1, UNCONFIRMED_CODE, outcome.message)
        else:
            self._release_photo(photo_key)
            code = outcome.error_code or "ERROR"
            if self._photo_rejected(task_id, job_id, code, photo_key, attempts, outcome.message):
                return True
            self._fail(task_id, job_id, attempts + 1, code, outcome.message)
        return True

    # ------------------------------------------------------------------
    # Varias cuentas a la vez (una cola y un navegador por cuenta)
    # ------------------------------------------------------------------
    def _job_is_parallel(self, job_id: int) -> bool:
        with self._db.session_scope() as session:
            job = session.get(PublishJob, job_id)
            return bool(job and job.parallel)

    def _coordinate_parallel(self, job_id: int) -> bool:
        """Arranca (o deja seguir) un hilo por cuenta con anuncios pendientes.

        Cada hilo publica SOLO los anuncios de su cuenta, en orden, con su
        propio navegador y respetando el ritmo de esa cuenta. Nunca hay dos
        hilos de la misma cuenta. Como mucho `max_parallel_accounts` a la vez."""
        with self._lanes_lock:
            alive = {r for r, t in self._lanes.items() if t.is_alive()}
            self._lanes = {r: t for r, t in self._lanes.items() if r in alive}
        with self._db.session_scope() as session:
            rows = session.execute(
                select(PublishTask.account_ref, PublishTask.status)
                .where(PublishTask.job_id == job_id)
                .order_by(PublishTask.position)
            ).all()
        pending: list[str] = []
        busy = False
        for ref, status in rows:
            if status is PublishTaskStatus.PENDING and ref not in pending:
                pending.append(ref)
            if status in (
                PublishTaskStatus.GENERATING, PublishTaskStatus.WAITING, PublishTaskStatus.PUBLISHING
            ):
                busy = True
        if busy and not alive:
            # Ningún hilo trabaja ya, pero quedan anuncios «en curso» (un fallo
            # inesperado): se dejan como tras un cierre (nada se duplica).
            self._recover_stale_tasks(job_id)
            return True
        if not pending and not busy and not alive:
            self._finish_job(job_id)
            return True
        usable = [r for r in pending if self._account_usable(r)]
        blocked = [r for r in pending if r not in usable]
        if blocked and not usable and not alive and not busy:
            self._pause_blocked(job_id, blocked)
            return True
        slots = int(self.settings()["max_parallel_accounts"]) - len(alive)
        started = False
        for ref in usable:
            if slots <= 0:
                break
            if ref in alive:
                continue
            self._start_lane(job_id, ref)
            slots -= 1
            started = True
        return started

    def _recover_stale_tasks(self, job_id: int) -> None:
        with self._db.session_scope() as session:
            for task in session.scalars(
                select(PublishTask).where(
                    PublishTask.job_id == job_id,
                    PublishTask.status.in_([
                        PublishTaskStatus.GENERATING,
                        PublishTaskStatus.WAITING,
                        PublishTaskStatus.PUBLISHING,
                    ]),
                )
            ).all():
                if task.status is PublishTaskStatus.PUBLISHING:
                    task.status = PublishTaskStatus.UNCONFIRMED
                    task.error = INTERRUPTED_MESSAGE
                    task.error_code = UNCONFIRMED_CODE
                else:
                    task.status = PublishTaskStatus.PENDING
        self._notify(job_id)

    def _start_lane(self, job_id: int, ref: str) -> None:
        thread = threading.Thread(
            target=self._lane, args=(job_id, ref), name=f"lotbot-cola-{ref}", daemon=True
        )
        with self._lanes_lock:
            self._lanes[ref] = thread
        thread.start()

    def _lane(self, job_id: int, ref: str) -> None:
        """Hilo de UNA cuenta: publica sus anuncios uno tras otro."""
        try:
            while not self._stop.is_set():
                if self._job_status(job_id) is not PublishJobStatus.RUNNING:
                    return
                if not self._account_usable(ref):
                    return
                with self._db.session_scope() as session:
                    task_id = session.scalar(
                        select(PublishTask.id)
                        .where(
                            PublishTask.job_id == job_id,
                            PublishTask.account_ref == ref,
                            PublishTask.status == PublishTaskStatus.PENDING,
                        )
                        .order_by(PublishTask.position)
                        .limit(1)
                    )
                if task_id is None:
                    return
                if not self._process_task(job_id, task_id, parallel=True):
                    return
        except Exception:  # pragma: no cover - un fallo raro no tumba las demás cuentas
            logger.exception("Error inesperado publicando en %s", ref)
        finally:
            self._wake.set()  # el coordinador mira si la cola ha terminado

    def wait_for_lanes(self, timeout: float = 30.0) -> None:
        """Espera a que acaben los hilos de las cuentas (pruebas y cierre)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lanes_lock:
                threads = [t for t in self._lanes.values() if t.is_alive()]
            if not threads or time.monotonic() > deadline:
                return
            for thread in threads:
                thread.join(max(0.0, min(1.0, deadline - time.monotonic())))

    def run_parallel_until_idle(self, max_rounds: int = 200) -> None:
        """Como `run_until_idle`, para colas «a la vez» (pruebas)."""
        for _ in range(max_rounds):
            worked = self.run_once()
            self.wait_for_lanes()
            if not worked and not self._lanes_alive():
                if self._active_job() is None or not self.run_once():
                    return

    def _lanes_alive(self) -> bool:
        with self._lanes_lock:
            return any(t.is_alive() for t in self._lanes.values())

    def _lane_ready_ts(self, ref: str, interval: int | None, attempts: int) -> float:
        """Cuándo puede publicar esta cuenta en una cola «a la vez»: su ritmo
        y, como mínimo, el intervalo de la cola desde SU último anuncio."""
        ready = self.account_ready_ts(ref)
        last = self._account_last_ts(ref)
        if last is not None:
            gap = max(interval or self.interval, MINIMUM_PUBLISH_INTERVAL_SECONDS)
            if attempts > 0:
                gap *= 2 ** min(attempts, 3)
            ready = max(ready, last + gap)
        return ready

    def _take_parallel_start(self) -> bool:
        """Separación corta entre los ARRANQUES de cuentas distintas (para no
        abrir todas las publicaciones en el mismo segundo)."""
        with self._lanes_lock:
            now = self.clock.now()
            last = self._last_parallel_start
            if last is not None and now - last < PARALLEL_START_GAP_S:
                return False
            self._last_parallel_start = now
            return True

    def _reset_failures(self) -> None:
        with self._lanes_lock:
            self._consecutive_failures = 0

    #: Espera entre borrados para hacer sitio (no son publicaciones).
    ROOM_DELETE_WAIT_S = 8.0

    def _make_room(self, job_id: int, account_ref: str) -> None:
        """Hace sitio si hace falta. NUNCA para la cola: si algo falla (p. ej.
        no se puede leer «Tus productos»), no se borra nada y se publica igual."""
        try:
            self._make_room_unsafe(job_id, account_ref)
        except Exception as exc:
            logger.warning("Límite de anuncios de %s: no se ha podido comprobar (%s). "
                           "No se borra nada.", account_ref, exc)

    def _make_room_unsafe(self, job_id: int, account_ref: str) -> None:
        """Si la cuenta ha llegado al máximo de anuncios, elimina los MÁS
        ANTIGUOS (los que hagan falta) antes de publicar el nuevo. Nunca toca
        nada si el límite está desactivado (0)."""
        limit = int(self.settings().get("max_listings_per_account") or 0)
        listings = getattr(self._app, "listings", None)
        publishing = getattr(self._app, "publishing", None)
        if limit <= 0 or listings is None or publishing is None:
            return
        from lot_bot.publishing.listings import ListingFilter

        # Al EMPEZAR la cola se lee la lista real de TODAS sus cuentas (solo
        # «Tus productos»; no se entra en ningún anuncio): así no hay lecturas
        # entre anuncio y anuncio. Después se cuenta con lo que se publica.
        synced = self.__dict__.setdefault("_room_synced", set())
        started = self.__dict__.setdefault("_room_started", set())
        if job_id not in started:
            started.add(job_id)
            for other in self._job_accounts(job_id):
                if other == account_ref or (job_id, other) in synced:
                    continue
                synced.add((job_id, other))
                try:
                    listings.sync_account(other)
                except Exception as exc:  # se volverá a probar con su primer anuncio
                    synced.discard((job_id, other))
                    logger.warning("No se ha podido leer la lista de %s: %s", other, exc)
        if (job_id, account_ref) not in synced:
            synced.add((job_id, account_ref))
            try:
                listings.sync_account(account_ref)
            except Exception as exc:
                # Sin la lista real no se sabe cuántos hay: no se borra a ciegas.
                synced.discard((job_id, account_ref))
                logger.warning("No se ha podido leer la lista de %s: %s", account_ref, exc)
                return
        active = [
            v for v in listings.search(ListingFilter(account_ref=account_ref, limit=5000))
            if v.status == "active"
        ]
        excess = len(active) - limit + 1
        if excess <= 0:
            return
        # Más antiguos primero: fecha de publicación (sin fecha = más antiguo).
        # Sin fecha (leídos de «Tus productos», que va de más nuevo a más
        # antiguo): cuanto más abajo en la lista (id mayor), más antiguo.
        oldest = sorted(
            active,
            key=lambda v: (
                v.published_at is not None,
                v.published_at or datetime.min,
                -v.id if v.published_at is None else v.id,
            ),
        )[:excess]
        logger.info(
            "%s tiene %d anuncios (máximo %d): se eliminan %d antiguos.",
            account_ref, len(active), limit, len(oldest),
        )
        outcomes = publishing.delete_listings(
            [v.id for v in oldest],
            confirmed=True,
            actor="LOT Bot (límite de anuncios)",
            interval_seconds=self.ROOM_DELETE_WAIT_S,
            sleep=lambda s: self.clock.sleep(s, self._stop),
        )
        failed = [o for o in outcomes if not o.success]
        self._audit.record_success(
            "Sitio hecho para publicar",
            account_ref=account_ref,
            detail=f"Eliminados {len(outcomes) - len(failed)} anuncio(s) antiguos (máximo {limit}).",
        )
        if failed:
            logger.warning("No se han podido eliminar %d antiguos: %s", len(failed), failed[0].message)

    def _job_accounts(self, job_id: int) -> list[str]:
        """Cuentas con anuncios pendientes en la cola (en orden)."""
        with self._db.session_scope() as session:
            refs = session.scalars(
                select(PublishTask.account_ref)
                .where(
                    PublishTask.job_id == job_id,
                    PublishTask.status == PublishTaskStatus.PENDING,
                )
                .order_by(PublishTask.position)
            ).all()
        seen: list[str] = []
        for ref in refs:
            if ref not in seen and self._account_usable(ref):
                seen.append(ref)
        return seen

    def _confirm_unconfirmed(self, job_id: int, account_ref: str | None = None) -> int:
        """Los anuncios que Wallapop no confirmó en pantalla se buscan en «Tus
        productos» (UNA lectura por cuenta). Devuelve cuántos se han confirmado.

        Un anuncio NO se reconoce solo por el título. En «Tus productos» se
        cuentan los anuncios NUEVOS (que no estaban en esa cuenta al empezar
        la cola ni son de otro anuncio ya publicado) con el MISMO título y el
        MISMO precio. Solo si salen exactamente los que faltan se dan por
        publicados (con su dirección). Si salen menos, más o sin precio, hay
        dudas: se quedan «sin confirmar» y se pide comprobarlo a mano."""
        from lot_bot.wallapop.capabilities import Capability

        service = getattr(self._app, "wallapop", None)
        listings = getattr(self._app, "listings", None)
        if service is None or listings is None:
            return 0
        with self._db.session_scope() as session:
            query = select(PublishTask).where(
                PublishTask.job_id == job_id,
                PublishTask.status == PublishTaskStatus.UNCONFIRMED,
            )
            if account_ref is not None:
                query = query.where(PublishTask.account_ref == account_ref)
            rows = [
                (t.id, t.account_ref, t.title or "", (t.payload or {}).get("precio"))
                for t in session.scalars(query.order_by(PublishTask.position)).all()
            ]
        if not rows:
            return 0
        try:
            if Capability.LIST_ITEMS not in service.capabilities():
                return 0
        except Exception:
            return 0
        by_account: dict[str, list[tuple[int, str, Any]]] = {}
        for task_id, ref, title, price in rows:
            by_account.setdefault(ref, []).append((task_id, title, price))
        confirmed = 0
        for ref, tasks in by_account.items():
            try:
                remote = service.list_items(ref, limit=500)
            except Exception as exc:  # comprobar nunca rompe la cola
                logger.warning("No se ha podido comprobar en «Tus productos»: %s", exc)
                continue
            known = self._known_listing_ids(job_id, ref)
            fresh = [item for item in remote if str(item.item_id) not in known]
            groups: dict[tuple[str, Any], list[int]] = {}
            for task_id, title, price in tasks:
                groups.setdefault((title, price), []).append(task_id)
            found: list[tuple[int, Any]] = []
            for (title, price), group in groups.items():
                matches, doubtful = _classify_items(fresh, title, price)
                # Anuncios de esta cola ya publicados con el mismo título y
                # precio pero sin dirección conocida: también están entre los nuevos.
                hidden = self._published_without_id(job_id, ref, title)
                expected = len(group) + hidden
                if price is not None and not doubtful and len(matches) == expected:
                    # Lo esperado, exactamente: se publicaron. «Tus productos»
                    # va del más nuevo al más antiguo; la cola, al revés.
                    ordered = list(reversed(matches))
                    for index, task_id in enumerate(group):
                        found.append((task_id, ordered[index] if not hidden else None))
                    continue
                reason = _doubt_reason(len(matches), expected, doubtful, price)
                for task_id in group:
                    self._set_task(task_id, error=reason[:1000], error_code=UNCONFIRMED_CODE)
                self._audit.record_error(
                    "Anuncio sin confirmar: hay que revisarlo a mano",
                    error=reason,
                    account_ref=ref,
                    target=title,
                )
            for task_id, item in found:
                url = (getattr(item, "raw", None) or {}).get("url") if item is not None else None
                self._set_task(
                    task_id,
                    status=PublishTaskStatus.PUBLISHED,
                    published_at=datetime.fromtimestamp(self.clock.now()),
                    remote_id=str(item.item_id) if item is not None else None,
                    remote_url=url,
                    error=None,
                    error_code=None,
                )
            if found:
                confirmed += len(found)
                try:
                    listings.sync_account(ref)  # quedan en «Anuncios» con su dirección
                except Exception as exc:
                    logger.warning("No se ha podido leer la lista de %s: %s", ref, exc)
        if confirmed:
            self._audit.record_success(
                "Anuncios sin confirmar encontrados en «Tus productos»",
                detail=f"Cola {job_id}: {confirmed} publicado(s) (mismo título y precio, anuncio nuevo)",
            )
        return confirmed

    def _known_listing_ids(self, job_id: int, ref: str) -> set[str]:
        """Anuncios que NO pueden ser el que se busca: los que ya tenía la
        cuenta al empezar la cola y los de otros anuncios ya publicados."""
        with self._db.session_scope() as session:
            row = session.get(Setting, KNOWN_LISTINGS_KEY.format(job=job_id))
            known = set(((row.value or {}) if row else {}).get(ref) or [])
            taken = session.scalars(
                select(PublishTask.remote_id).where(
                    PublishTask.account_ref == ref,
                    PublishTask.status == PublishTaskStatus.PUBLISHED,
                    PublishTask.remote_id.is_not(None),
                )
            ).all()
        if row is None or ref not in (row.value or {}):
            # Cola antigua (sin foto de lo que había): se usa lo que LOT Bot conoce.
            known |= self._local_listing_ids(ref)
        return known | {str(t) for t in taken}

    def _local_listing_ids(self, ref: str) -> set[str]:
        from lot_bot.publishing.listings import ListingFilter

        listings = getattr(self._app, "listings", None)
        if listings is None:
            return set()
        # Los ya eliminados no están en la cuenta: no cuentan como «lo que había».
        return {
            str(v.wallapop_item_id)
            for v in listings.search(ListingFilter(account_ref=ref, limit=5000))
            if v.wallapop_item_id and v.status != "removed"
        }

    def _remember_known_listings(self, job_id: int, ref: str) -> None:
        """Antes del PRIMER anuncio de una cuenta en esta cola se apunta qué
        anuncios tenía ya (lo que conoce LOT Bot). Así, si luego Wallapop no
        confirma uno, se sabe cuáles de «Tus productos» son nuevos."""
        key = KNOWN_LISTINGS_KEY.format(job=job_id)
        with self._state_lock:
            with self._db.session_scope() as session:
                row = session.get(Setting, key)
                if row is not None and ref in (row.value or {}):
                    return
            try:
                ids = sorted(self._local_listing_ids(ref))
            except Exception:
                logger.debug("No se han podido leer los anuncios de %s", ref, exc_info=True)
                return
            with self._db.session_scope() as session:
                row = session.get(Setting, key)
                if row is None:
                    session.add(Setting(key=key, value={ref: ids}))
                else:
                    row.value = {**(row.value or {}), ref: ids}

    def _published_without_id(self, job_id: int, ref: str, title: str) -> int:
        """Anuncios de esta cola publicados (y confirmados) sin dirección real."""
        with self._db.session_scope() as session:
            ids = session.scalars(
                select(PublishTask.remote_id).where(
                    PublishTask.job_id == job_id,
                    PublishTask.account_ref == ref,
                    PublishTask.title == title,
                    PublishTask.status == PublishTaskStatus.PUBLISHED,
                )
            ).all()
        return sum(1 for i in ids if not i or str(i).startswith("navegador-"))

    def _forget_job_state(self, job_id: int) -> None:
        """Al terminar la cola se borra lo que solo servía mientras estaba en marcha."""
        self._accepted_missing.discard(job_id)
        self._missing_warned.pop(job_id, None)
        with self._db.session_scope() as session:
            row = session.get(Setting, KNOWN_LISTINGS_KEY.format(job=job_id))
            if row is not None:
                # Si queda alguno sin confirmar, se conserva para volver a mirarlo.
                pending = session.scalar(
                    select(func.count(PublishTask.id)).where(
                        PublishTask.job_id == job_id,
                        PublishTask.status == PublishTaskStatus.UNCONFIRMED,
                    )
                )
                if not pending:
                    session.delete(row)

    # ------------------------------------------------------------------
    # Ritmo por cuenta
    # ------------------------------------------------------------------
    def _account_last_ts(self, ref: str) -> float | None:
        if ref in self._account_last:
            return self._account_last[ref]
        if not self.clock.is_real:
            return None
        with self._db.session_scope() as session:
            last = session.scalar(
                select(func.max(PublishTask.started_at)).where(PublishTask.account_ref == ref)
            )
        return last.timestamp() if last is not None else None

    def account_ready_ts(self, ref: str, settings: dict[str, Any] | None = None) -> float:
        """Cuándo puede volver a publicar esta cuenta según SU ritmo."""
        settings = settings or self.settings()
        now = self.clock.now()
        ready = now
        last = self._account_last_ts(ref)
        if last is not None:
            gap = float(settings["account_interval_seconds"])
            if self._account_slow_until.get(ref, 0.0) > now:
                gap *= SLOWDOWN_FACTOR
            ready = max(ready, last + gap)
        return max(ready, self._account_rest_until.get(ref, 0.0))

    def _ready_ts(self, ref: str, interval: int | None, attempts: int) -> float:
        return max(self.next_allowed_ts(interval, attempts), self.account_ready_ts(ref))

    def _pick_by_pace(self, candidates: list[Any]) -> Any:
        """El primer anuncio cuya cuenta ya puede publicar; si ninguna puede,
        el de la cuenta que antes podrá (las demás no se quedan esperando)."""
        if not candidates:
            return None
        settings = self.settings()
        now = self.clock.now()
        ready: dict[str, float] = {}
        for task in candidates:
            if task.account_ref not in ready:
                ready[task.account_ref] = self.account_ready_ts(task.account_ref, settings)
            if ready[task.account_ref] <= now:
                return task
        return min(candidates, key=lambda t: (ready[t.account_ref], t.position))

    def _account_attempted(self, ref: str) -> None:
        """Se va a publicar en `ref`: cuenta para el ritmo y los descansos."""
        settings = self.settings()
        now = self.clock.now()
        last = self._account_last_ts(ref)
        rest_s = int(settings["batch_rest_minutes"]) * 60
        streak = self._account_streak.get(ref, 0)
        if last is not None and rest_s and now - last >= rest_s:
            streak = 0  # ya ha descansado lo suyo por su cuenta
        streak += 1
        self._account_last[ref] = now
        batch = int(settings["batch_size"])
        if batch and rest_s and streak >= batch:
            self._account_rest_until[ref] = now + rest_s
            streak = 0
            logger.info("%s: %d anuncios seguidos; descansa %d min.", ref, batch, rest_s // 60)
        self._account_streak[ref] = streak

    def _slow_down(self, ref: str) -> None:
        """Wallapop ha pedido una verificación: esta cuenta va más despacio."""
        hours = int(self.settings()["slowdown_hours"])
        if hours > 0:
            self._account_slow_until[ref] = self.clock.now() + hours * 3600

    def pacing_notes(self) -> list[str]:
        """Qué cuentas descansan o van más despacio ahora (para la pantalla)."""
        now = self.clock.now()
        refs = set(self._account_rest_until) | set(self._account_slow_until)
        if not refs:
            return []
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        notes = []
        for ref in sorted(refs):
            name = aliases.get(ref, ref)
            rest = self._account_rest_until.get(ref, 0.0)
            if rest > now:
                notes.append(
                    f"«{name}» descansa hasta las {datetime.fromtimestamp(rest):%H:%M} "
                    "(tras varios anuncios seguidos); las demás cuentas siguen."
                )
            slow = self._account_slow_until.get(ref, 0.0)
            if slow > now:
                notes.append(
                    f"«{name}» publica más despacio hasta las "
                    f"{datetime.fromtimestamp(slow):%H:%M} (Wallapop pidió una verificación)."
                )
        return notes

    def _unconfirmed_found_now(
        self, task_id: int, job_id: int, ref: str, message: str, photo_key: str | None
    ) -> bool:
        """Anuncio sin confirmar. Normalmente se comprueba al FINAL de la cola
        (sin lecturas entre anuncios). Solo si ya van varios fallos seguidos
        (la cola se pausaría) se mira ahora «Tus productos» de esa cuenta."""
        if photo_key:
            self.mark_photo_used(photo_key, ref)  # pudo publicarse: no se repite
        if self._consecutive_failures + 1 < MAX_CONSECUTIVE_FAILURES:
            return False
        self._set_task(task_id, status=PublishTaskStatus.UNCONFIRMED, error=message[:1000],
                       error_code=UNCONFIRMED_CODE)
        self._confirm_unconfirmed(job_id, account_ref=ref)
        with self._db.session_scope() as session:
            return session.get(PublishTask, task_id).status is PublishTaskStatus.PUBLISHED

    # ------------------------------------------------------------------
    def _generate_image(
        self, task_id: int, job_id: int, position: int, ref: str, payload: dict[str, Any]
    ) -> str | None:
        from lot_bot.images.generation import GenerationError, spec_from_master

        master = self._app.master_ads.get(payload.get("master_key"))
        overrides = payload.get("overrides") or {}
        spec = spec_from_master(master, size=overrides.get("medida"))
        try:
            result = self._app.image_generation.generate_unique(
                spec,
                variation=job_id * 17 + position,
                subject=f"Cola {job_id} · anuncio {position} · {master.name}",
                account_ref=ref,
                task_id=task_id,
                preferred_rooms=self._preferred_rooms(),
            )
        except GenerationError as exc:
            self._fail(task_id, job_id, 1, exc.code, exc.user_message, allow_retry=exc.code != "DUPLICATE")
            return None
        except Exception as exc:
            self._fail(task_id, job_id, 1, type(exc).__name__, str(exc))
            return None
        # Se guarda qué escena se usó: servirá para analizar qué funciona mejor.
        payload["imagen"] = {
            "id": result.image_id,
            "escena": dict(result.scene),
            "proveedor": result.provider,
            "operacion": result.operation,
            "demo": result.is_demo,
        }
        self._set_task(task_id, image_path=str(result.path), payload=dict(payload))
        self._audit.record_success(
            "Imagen generada para anuncio",
            account_ref=ref,
            target=master.name,
            detail=f"{result.provider}; intento {result.attempts}; {result.path.name}",
        )
        return str(result.path)

    # ------------------------------------------------------------------
    # Fotos ya publicadas: NUNCA se repiten (en ninguna cuenta)
    # ------------------------------------------------------------------
    @staticmethod
    def photo_key(image: dict[str, Any]) -> str:
        """Identifica la foto por su contenido (si se conoce) o por su ruta."""
        return str(image.get("content_hash") or image.get("path") or "")

    def used_photos(self) -> dict[str, dict[str, Any]]:
        """{foto: {"cuentas": [...], "fecha": ...}} de las fotos ya publicadas."""
        with self._db.session_scope() as session:
            row = session.get(Setting, USED_PHOTOS_KEY)
            return dict((row.value or {}) if row else {})

    def _save_used(self, used: dict[str, dict[str, Any]]) -> None:
        with self._db.session_scope() as session:
            row = session.get(Setting, USED_PHOTOS_KEY)
            if row is None:
                session.add(Setting(key=USED_PHOTOS_KEY, value=used))
            else:
                row.value = used

    def mark_photo_used(self, key: str, account_ref: str) -> None:
        with self._state_lock:
            used = self.used_photos()
            entry = dict(used.get(key) or {"cuentas": []})
            entry["cuentas"] = sorted({*entry.get("cuentas", []), account_ref})
            entry["fecha"] = datetime.fromtimestamp(self.clock.now()).isoformat(timespec="seconds")
            used[key] = entry
            self._save_used(used)
            self._reserved_photos.pop(key, None)

    def reset_used_photos(self) -> None:
        """Permite volver a usar todas las fotos (lo decide el usuario).
        También las que Wallapop rechazó: se volverán a probar."""
        with self._state_lock:
            self._save_used({})
            self._save_setting(REJECTED_PHOTOS_KEY, {})
        self._audit.record_success("Fotos publicadas reiniciadas", actor="usuario")

    # --- Fotos que faltan o están dañadas -----------------------------
    _photo_checks: dict[tuple[str, float, int], str | None] = {}

    @classmethod
    def photo_problem(cls, path: str | None) -> str | None:
        """None si la foto se puede subir; si no, por qué («no está en el
        ordenador», «está dañada»). El resultado se recuerda mientras el
        fichero no cambie."""
        if not path:
            return "no tiene ruta"
        file = Path(path)
        try:
            stat = file.stat()
        except OSError:
            return "no está en el ordenador (se borró o se movió)"
        if not file.is_file():
            return "no está en el ordenador (se borró o se movió)"
        key = (str(file), stat.st_mtime, stat.st_size)
        if key not in cls._photo_checks:
            problem = None
            try:
                from PIL import Image

                with Image.open(file) as img:
                    img.verify()
            except Exception:
                problem = "está dañada o no es una imagen"
            cls._photo_checks[key] = problem
        return cls._photo_checks[key]

    def rejected_photos(self) -> dict[str, dict[str, Any]]:
        with self._db.session_scope() as session:
            row = session.get(Setting, REJECTED_PHOTOS_KEY)
            return dict((row.value or {}) if row else {})

    def _save_setting(self, key: str, value: Any) -> None:
        with self._db.session_scope() as session:
            row = session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=value))
            else:
                row.value = value

    def missing_photos(self, master_key: str | None) -> list[dict[str, str]]:
        """Fotos MARCADAS del anuncio principal que no se pueden subir
        (borradas, movidas o dañadas): [{"nombre", "ruta", "motivo"}]."""
        master = self._app.master_ads.get(master_key)
        if master is None:
            return []
        problems = []
        for image in self._app.master_ads.effective_images(master):
            if image.get("source") == "demo":
                continue
            problem = self.photo_problem(image.get("path"))
            if problem:
                path = str(image.get("path") or "")
                problems.append({"nombre": Path(path).name or "(sin nombre)", "ruta": path,
                                 "motivo": problem})
        return problems

    def unused_photos(self, master_key: str | None) -> list[dict[str, Any]]:
        """Fotos marcadas del anuncio principal que aún no se han publicado
        (y que se pueden subir: existen, no están dañadas y Wallapop no las
        ha rechazado)."""
        master = self._app.master_ads.get(master_key)
        if master is None:
            return []
        used = self.used_photos()
        rejected = self.rejected_photos()
        unused = [
            i for i in self._app.master_ads.effective_images(master)
            if i.get("source") != "demo" and self.photo_key(i) not in used
            and self.photo_key(i) not in rejected
        ]
        # Una foto borrada o dañada no se puede subir: si se eligiera, fallarían
        # uno tras otro todos los anuncios (siempre sería «la siguiente»). Se
        # salta y se avisa (en el registro y en el historial).
        present = [i for i in unused if not self.photo_problem(i.get("path"))]
        if len(present) < len(unused):
            logger.warning(
                "%d foto(s) marcada(s) del Anuncio principal no se pueden subir: se saltan.",
                len(unused) - len(present),
            )
        return present

    def _has_own_photos(self, master_key: str | None) -> bool:
        """¿El anuncio principal tiene fotos tuyas marcadas? Sin ninguna (solo
        las de demostración), no hay nada que rotar y se publica como siempre."""
        master = self._app.master_ads.get(master_key)
        return master is not None and any(
            i.get("source") != "demo" for i in self._app.master_ads.effective_images(master)
        )

    def _next_rotating_photo(self, master_key: str | None) -> dict[str, Any] | None:
        """La primera foto marcada que todavía no se ha publicado en NINGUNA
        cuenta (en el orden de «Fotografías…») ni está elegida por otro anuncio."""
        with self._state_lock:
            for photo in self.unused_photos(master_key):
                if self.photo_key(photo) not in self._reserved_photos:
                    return photo
        return None

    def _reserve_photo(
        self, master_key: str | None, task_id: int, job_id: int
    ) -> dict[str, Any] | None:
        """Elige la foto de este anuncio y la aparta: con varias cuentas a la
        vez, dos anuncios nunca cogen la misma foto."""
        self._warn_skipped_photos(job_id, master_key)
        with self._state_lock:
            photo = self._next_rotating_photo(master_key)
            if photo is not None:
                self._reserved_photos[self.photo_key(photo)] = task_id
            return photo

    def _release_photo(self, key: str | None, *, used: bool = False) -> None:
        """La foto apartada vuelve a estar libre (el anuncio no se publicó)."""
        if not key:
            return
        with self._state_lock:
            self._reserved_photos.pop(key, None)

    def _warn_skipped_photos(self, job_id: int, master_key: str | None) -> None:
        """Avisa (una vez por cola y foto) de las fotos que se saltan."""
        for photo in self.missing_photos(master_key):
            mark = (job_id, photo["ruta"])
            if mark in self._photo_warned:
                continue
            self._photo_warned.add(mark)
            self._audit.record_error(
                "Foto del Anuncio principal que no se puede subir (se salta)",
                error=f"«{photo['nombre']}» {photo['motivo']}.",
                detail="Vuelve a añadirla en «Anuncio principal» → «Fotografías…».",
            )
            self._notify(job_id)

    def _photos_ok_to_publish(self, job_id: int, master_key: str | None) -> bool:
        """Sin «no repetir fotos» se suben TODAS las marcadas. Si falta alguna,
        no se publica con menos sin avisar: la cola se pausa y lo explica. Si
        la persona pulsa «Continuar», esta cola sigue con las que quedan."""
        missing = self.missing_photos(master_key)
        if not missing or job_id in self._accepted_missing:
            return True
        master = self._app.master_ads.get(master_key)
        total = len([
            i for i in self._app.master_ads.effective_images(master) if i.get("source") != "demo"
        ]) if master else 0
        names = [f"«{m['nombre']}» ({m['motivo']})" for m in missing]
        self._missing_warned[job_id] = [m["nombre"] for m in missing]
        self._audit.record_error(
            "Faltan fotos del Anuncio principal",
            error="; ".join(names),
            detail=f"Cola {job_id}: pausada hasta que las añadas o pulses «Continuar».",
        )
        self.pause(
            job_id,
            MISSING_PHOTOS_MESSAGE.format(
                n=len(missing), names=", ".join(names), left=max(0, total - len(missing))
            ),
        )
        return False

    def _photo_rejected(
        self, task_id: int, job_id: int, code: str, photo_key: str | None, attempts: int,
        message: str,
    ) -> bool:
        """Wallapop ha rechazado la foto de este anuncio. Con «no repetir
        fotos», esa foto se aparta (no se vuelve a elegir) y el anuncio vuelve
        a la cola con la siguiente, sin contar como fallo: una foto mala no
        bloquea la cola."""
        # Solo si Wallapop la RECHAZA: si tarda en cargar (red lenta) no es
        # culpa de la foto y no se aparta.
        if code != "ImageUploadError" or not photo_key or "rechaz" not in message.lower():
            return False
        with self._state_lock:
            rejected = self.rejected_photos()
            rejected[photo_key] = {
                "motivo": message[:200],
                "fecha": datetime.fromtimestamp(self.clock.now()).isoformat(timespec="seconds"),
            }
            self._save_setting(REJECTED_PHOTOS_KEY, rejected)
        self._set_task(
            task_id,
            status=PublishTaskStatus.PENDING,
            attempts=attempts,
            error="Wallapop rechazó la foto de este anuncio: se apartará y se usará la siguiente.",
            error_code="FOTO_RECHAZADA",
        )
        self._audit.record_error(
            "Wallapop ha rechazado una foto (se aparta y se sigue)",
            error=message[:300],
            detail=f"Cola {job_id}",
        )
        return True

    def _preferred_rooms(self) -> list[str]:
        """Habitaciones que mejor han funcionado (si hay datos suficientes)."""
        optimizer = getattr(self._app, "optimizer", None)
        if optimizer is None:
            return []
        try:
            return optimizer.preferred_rooms()
        except Exception:  # la optimización nunca debe parar la cola
            logger.debug("Optimizador no disponible", exc_info=True)
            return []

    def _set_task(self, task_id: int, **fields: Any) -> None:
        with self._db.session_scope() as session:
            task = session.get(PublishTask, task_id)
            for key, value in fields.items():
                setattr(task, key, value)
            job_id = task.job_id
        self._notify(job_id)

    def _fail(
        self,
        task_id: int,
        job_id: int,
        attempts: int,
        code: str,
        message: str,
        *,
        allow_retry: bool = True,
    ) -> None:
        if code == "AuthenticationError":
            self._session_expired(task_id, job_id, attempts, message)
            return
        settings = self.settings()
        pausing = code in PAUSING_ERRORS
        retry = (
            allow_retry
            and not pausing
            and code not in NON_RETRYABLE
            and attempts <= int(settings["automatic_retries"])
        )
        with self._db.session_scope() as session:
            task = session.get(PublishTask, task_id)
            task.attempts = attempts
            task.error = message[:1000]
            task.error_code = code[:80]
            if code == UNCONFIRMED_CODE:
                task.status = PublishTaskStatus.UNCONFIRMED
            else:
                task.status = PublishTaskStatus.PENDING if retry else PublishTaskStatus.FAILED
            ref, title = task.account_ref, task.title
        self._audit.record_error(
            "Publicación en cola fallida" + (" (se reintentará)" if retry else ""),
            error=f"{code}: {message}",
            account_ref=ref,
            target=title,
        )
        with self._lanes_lock:
            self._consecutive_failures += 1
        if code == "VerificationRequiredError":
            self._slow_down(ref)
        if pausing:
            self.pause(job_id, message)
        elif self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.pause(
                job_id,
                f"Han fallado {self._consecutive_failures} anuncios seguidos (el último: "
                f"{message[:200]}). Puede que Wallapop haya cambiado algo: revisa el error "
                "y pulsa «Continuar».",
            )
        elif code in SKIPPING_ERRORS:
            logger.info("Anuncio no publicado (%s); la cola sigue con el siguiente.", code)
        self._notify(job_id)

    def _user_gate(
        self,
        account_ref: str,
        message: str,
        *,
        solved: Callable[[], bool] | None = None,
        can_defer: bool = False,
        focus: Callable[[], Any] | None = None,
    ) -> Any:
        """Espera a la persona. La llama el navegador (desde SU hilo) cuando
        Wallapop pide una verificación o hay que iniciar sesión.

        * Verificación (`solved` dado): la cuenta queda marcada para que la
          interfaz avise. Si hay anuncios de OTRAS cuentas y aún no se ha
          pulsado «Publicar» (`can_defer`), devuelve GATE_DEFER: este anuncio
          se hace después y la cola sigue con las demás. Si no, la cola se
          pausa aquí y, en cuanto `solved()` dice que la verificación ha
          desaparecido, se reanuda SOLA y se sigue desde el mismo paso.
        * Lo demás: la cola se pausa y se sigue al pulsar «Continuar».

        Sin límite de tiempo. True = seguir; False = cancelada o LOT Bot se cierra.
        """
        job_id = getattr(self, "_current_job", None)
        if job_id is None:
            return False
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        alias = aliases.get(account_ref, account_ref)
        if solved is not None and self._job_is_parallel(job_id):
            return self._wait_verification_in_lane(job_id, account_ref, solved, focus)
        if solved is not None:
            defer = can_defer and self._others_can_publish(job_id, account_ref)
            self._verification_started(account_ref, job_id, deferred=defer)
            if defer:
                return GATE_DEFER
            self.pause(job_id, f"{alias}: {VERIFICATION_WAIT_MESSAGE}")
        else:
            self.pause(job_id, f"{alias}: {message}")
        deadline = None if USER_GATE_TIMEOUT_S is None else time.monotonic() + USER_GATE_TIMEOUT_S
        next_check = 0.0
        try:
            while not self._stop.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                status = self._job_status(job_id)
                if status is PublishJobStatus.RUNNING:
                    return True  # «Continuar»
                if status in (PublishJobStatus.CANCELLED, PublishJobStatus.COMPLETED):
                    return False
                if focus is not None and self._take_focus_request(account_ref):
                    try:
                        focus()  # «Mostrar la ventana de Chrome» (desde este hilo)
                    except Exception:
                        logger.debug("No se ha podido poner la ventana delante", exc_info=True)
                if solved is not None and time.monotonic() >= next_check:
                    next_check = time.monotonic() + 1.0
                    try:
                        done = bool(solved())
                    except Exception:
                        logger.debug("No se ha podido mirar la verificación", exc_info=True)
                        done = False
                    if done:
                        if self._job_status(job_id) is PublishJobStatus.PAUSED:
                            self.resume(job_id)
                        return True
                self._stop.wait(0.3)
            return False
        finally:
            if solved is not None:
                self._verification_cleared(account_ref)

    def _wait_verification_in_lane(
        self,
        job_id: int,
        account_ref: str,
        solved: Callable[[], bool],
        focus: Callable[[], Any] | None,
    ) -> bool:
        """Cola «a la vez»: Wallapop pide una verificación en UNA cuenta. Esa
        cuenta espera a la persona (sin límite y sin resolverla nunca); las
        demás siguen publicando. En cuanto desaparece, sigue sola desde el
        mismo paso. False si la cola se cancela o LOT Bot se cierra."""
        self._verification_started(account_ref, job_id, deferred=False)
        try:
            next_check = 0.0
            while not self._stop.is_set():
                if self._job_status(job_id) in (PublishJobStatus.CANCELLED, PublishJobStatus.COMPLETED):
                    return False
                if focus is not None and self._take_focus_request(account_ref):
                    try:
                        focus()
                    except Exception:
                        logger.debug("No se ha podido poner la ventana delante", exc_info=True)
                if time.monotonic() >= next_check:
                    next_check = time.monotonic() + 1.0
                    try:
                        if solved():
                            return True
                    except Exception:
                        logger.debug("No se ha podido mirar la verificación", exc_info=True)
                self._stop.wait(0.3)
            return False
        finally:
            self._verification_cleared(account_ref)

    # ------------------------------------------------------------------
    # Verificaciones de Wallapop (las completa SIEMPRE la persona)
    # ------------------------------------------------------------------
    def verifying_accounts(self) -> set[str]:
        with self._verifying_lock:
            return set(self._verifying)

    def pending_verifications(self) -> list[dict[str, Any]]:
        """Cuentas en las que Wallapop pide ahora una verificación (para avisar)."""
        with self._verifying_lock:
            items = [(ref, dict(info)) for ref, info in self._verifying.items()]
        if not items:
            return []
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        return [
            {
                "cuenta_ref": ref,
                "cuenta": aliases.get(ref, ref),
                "desde": info["desde"],
                "aplazada": info["aplazada"],
                "cola": info["cola"],
            }
            for ref, info in sorted(items, key=lambda item: item[1]["desde"])
        ]

    def show_verification_window(self, ref: str) -> None:
        """Vuelve a poner delante la ventana de la cuenta con la verificación.

        Si el navegador está esperando a la persona (mismo paso), lo hace él
        mismo en cuanto lo ve; si el anuncio se aplazó, se pide al navegador."""
        with self._verifying_lock:
            info = self._verifying.get(ref)
            if info is None:
                return
            if not info["aplazada"]:
                self._focus_requests.add(ref)
                return
        service = getattr(self._app, "wallapop", None)
        show = getattr(service, "show_window", None)
        if callable(show):
            show(ref)

    def _take_focus_request(self, ref: str) -> bool:
        with self._verifying_lock:
            if ref in self._focus_requests:
                self._focus_requests.discard(ref)
                return True
            return False

    def _verification_started(self, ref: str, job_id: int, *, deferred: bool) -> None:
        self._slow_down(ref)
        with self._verifying_lock:
            new = ref not in self._verifying
            self._verifying[ref] = {
                "cola": job_id,
                "desde": (self._verifying.get(ref) or {}).get("desde") or datetime.now(),
                "aplazada": deferred,
            }
        if new:
            self._audit.record_error(
                "Wallapop pide una verificación",
                error="La tiene que completar la persona en la ventana de la cuenta.",
                account_ref=ref,
                detail="Se publica en las demás cuentas mientras tanto" if deferred else None,
            )
        self._notify(job_id)

    def _verification_cleared(self, ref: str) -> None:
        with self._verifying_lock:
            info = self._verifying.pop(ref, None)
            self._focus_requests.discard(ref)
        if info is None:
            return
        self._audit.record_success("Verificación completada: la publicación sigue", account_ref=ref)
        self._notify(info["cola"])
        self._wake.set()

    def _others_can_publish(self, job_id: int, ref: str) -> bool:
        """¿Hay anuncios pendientes de OTRAS cuentas que se puedan publicar ya?"""
        verifying = self.verifying_accounts()
        with self._db.session_scope() as session:
            others = set(
                session.scalars(
                    select(PublishTask.account_ref).where(
                        PublishTask.job_id == job_id,
                        PublishTask.status == PublishTaskStatus.PENDING,
                        PublishTask.account_ref != ref,
                    )
                ).all()
            )
        return any(r not in verifying and self._account_usable(r) for r in others)

    def _defer_task(self, task_id: int, attempts: int) -> None:
        """El anuncio vuelve a la cola (sin contar como intento ni como fallo)
        hasta que la persona complete la verificación de su cuenta."""
        self._set_task(
            task_id,
            status=PublishTaskStatus.PENDING,
            attempts=attempts,
            error=VERIFICATION_TASK_MESSAGE,
            error_code=VERIFICATION_CODE,
        )

    def _poll_verifications(self, *, force: bool = False) -> None:
        """Mira (sin tocar nada) si ya han desaparecido las verificaciones de
        las cuentas aplazadas. Si la ventana se ha cerrado, se vuelve a probar
        con esa cuenta: si Wallapop la sigue pidiendo, se avisará otra vez."""
        now = time.monotonic()
        if not force and now - self._last_verification_poll < VERIFICATION_POLL_S:
            return
        self._last_verification_poll = now
        with self._verifying_lock:
            deferred = [r for r, info in self._verifying.items() if info["aplazada"]]
        if not deferred:
            return
        service = getattr(self._app, "wallapop", None)
        look = getattr(service, "verification_pending", None)
        for ref in deferred:
            try:
                pending = look(ref) if callable(look) else None
            except Exception:
                logger.debug("No se ha podido mirar la verificación de %s", ref, exc_info=True)
                pending = True
            if not pending:
                self._verification_cleared(ref)
        if not force:
            return
        # Nada más que hacer hasta que la persona complete alguna: espera corta.
        if self.verifying_accounts():
            self._stop.wait(1.0)

    def account_reconnected(self, account_ref: str) -> list[int]:
        """Tras «Reconectar» una cuenta cuya sesión caducó, las colas que
        esperaban por ella continúan solas. Devuelve las colas reanudadas."""
        resumed: list[int] = []
        with self._db.session_scope() as session:
            jobs = session.scalars(
                select(PublishJob).where(PublishJob.status == PublishJobStatus.PAUSED)
            ).all()
            candidates = []
            for job in jobs:
                waiting = session.scalars(
                    select(PublishTask).where(
                        PublishTask.job_id == job.id,
                        PublishTask.account_ref == account_ref,
                        PublishTask.status == PublishTaskStatus.PENDING,
                        PublishTask.error_code == RELOGIN_CODE,
                    )
                ).first()
                if waiting is not None:
                    candidates.append(job.id)
        for job_id in candidates:
            self.resume(job_id)
            resumed.append(job_id)
        return resumed

    def _account_usable(self, ref: str) -> bool:
        from lot_bot.database.models import AccountStatus

        info = self._app.accounts.get_account(ref)
        return info is not None and info.status == AccountStatus.CONNECTED

    def _session_expired(self, task_id: int, job_id: int, attempts: int, message: str) -> None:
        """Wallapop pide volver a iniciar sesión en una cuenta.

        La cuenta NO se marca como caducada (en LOT Bot las cuentas solo dejan
        de funcionar si el usuario las elimina). El anuncio vuelve a la cola y
        la cola se pausa hasta que el usuario entre y pulse «Continuar» (o
        «Reconectar», que la reanuda sola)."""
        with self._db.session_scope() as session:
            task = session.get(PublishTask, task_id)
            task.attempts = max(0, attempts - 1)  # no cuenta como intento fallido
            task.error = message[:1000]
            task.error_code = RELOGIN_CODE
            task.status = PublishTaskStatus.PENDING
            ref, title = task.account_ref, task.title
        self._audit.record_error(
            "Wallapop pide iniciar sesión de nuevo (la cuenta sigue conectada)",
            error=message,
            account_ref=ref,
            target=title,
        )
        aliases = {a.internal_ref: a.alias for a in self._app.accounts.list_accounts()}
        if "Continuar" not in message:
            message += " Inicia sesión en la ventana de la cuenta y pulsa «Continuar»."
        self.pause(job_id, f"{aliases.get(ref, ref)}: {message}")

    def _notify(self, job_id: int) -> None:
        for listener in list(self.listeners):
            try:
                listener(job_id)
            except Exception:  # la interfaz nunca debe tumbar la cola
                logger.debug("Aviso de la cola fallido", exc_info=True)


# ---------------------------------------------------------------------------
# Reconocer un anuncio en «Tus productos» (sin fiarse solo del título)
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    from lot_bot.publishing.listings import _norm_text

    return _norm_text(text or "")


def _same_title(wanted: str, item: Any) -> bool:
    """¿Es el mismo título? Igual, o contenido en el texto de la ficha, o
    la ficha lo muestra recortado («Canapé abatible 135x190…»)."""
    wanted = _norm(wanted)
    if not wanted:
        return False
    shown = _norm(getattr(item, "title", "") or "")
    text = _norm((getattr(item, "raw", None) or {}).get("texto") or "")
    if shown == wanted or (text and wanted in text):
        return True
    cut = shown.rstrip(" .…")
    return len(cut) >= 20 and wanted.startswith(cut)


def _classify_items(items: list[Any], title: str, price: Any) -> tuple[list[Any], list[Any]]:
    """(coinciden en título Y precio, mismo título pero precio desconocido)."""
    matches, doubtful = [], []
    for item in items:
        if not _same_title(title, item):
            continue
        shown = getattr(item, "price", None)
        if shown is None or price is None:
            doubtful.append(item)
        elif abs(float(shown) - float(price)) < 0.01:
            matches.append(item)
    return matches, doubtful


def _doubt_reason(found: int, expected: int, doubtful: list[Any], price: Any) -> str:
    base = "Comprobación manual: Wallapop no confirmó este anuncio y LOT Bot no puede asegurar si se publicó. "
    if price is None:
        detail = "No se sabe con qué precio se publicó (cola antigua)."
    elif doubtful:
        detail = f"En «Tus productos» hay {len(doubtful)} anuncio(s) nuevos con el mismo título pero sin precio visible."
    elif found == 0:
        detail = "En «Tus productos» no aparece ningún anuncio nuevo con el mismo título y precio: probablemente NO se publicó."
    elif found < expected:
        detail = f"En «Tus productos» hay {found} anuncio(s) nuevos con el mismo título y precio, y faltan {expected}."
    else:
        detail = f"En «Tus productos» hay {found} anuncio(s) nuevos con el mismo título y precio (se esperaban {expected}): alguno pudo publicarse a mano."
    return base + detail + " Míralo en Wallapop y, si NO está, pulsa «Reintentar anuncio fallido»."
