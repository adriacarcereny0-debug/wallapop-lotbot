"""«Primeros pasos»: guía para empezar con LOT Bot, pensada para quien no sabe
de informática.

Cinco pasos con una marca de hecho/pendiente que LOT Bot calcula solo (no hay
que marcar nada) y un botón «Ir» que abre la pantalla de cada paso. Sale sola
al abrir LOT Bot mientras falte algo (se puede desactivar) y está siempre en
Configuración → Acerca de → «Primeros pasos».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lot_bot.ui import theme

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

SETTING_KEY = "primeros_pasos"


@dataclass(frozen=True)
class Step:
    title: str
    detail: str
    done: bool
    #: Pantalla a la que lleva «Ir» (nombre de NAVIGATION) y pestaña opcional.
    section: str
    tab: str | None = None


def _published_count(app: Application) -> int:
    from sqlalchemy import func, select

    from lot_bot.database.models import PublishTask, PublishTaskStatus

    with app.db.session_scope() as session:
        return int(
            session.scalar(
                select(func.count(PublishTask.id)).where(PublishTask.status == PublishTaskStatus.PUBLISHED)
            )
            or 0
        )


def onboarding_steps(app: Application) -> list[Step]:
    demo = app.demo_mode
    steps: list[Step] = []

    manager = getattr(app, "license", None)
    status = manager.status() if manager is not None else None
    if demo:
        steps.append(Step(
            "Licencia",
            "Estás en modo DEMO (gratis): pruebas sin tocar Wallapop. Para publicar de verdad, activa tu "
            "licencia y elige «Navegador» en Configuración → Wallapop.",
            True, "Configuración", "Licencia",
        ))
    else:
        steps.append(Step(
            "Activa tu licencia",
            "Escribe la clave que te enviamos (LOTB-…) en Configuración → Licencia.",
            bool(status and status.allowed), "Configuración", "Licencia",
        ))

    try:
        accounts = app.accounts.list_accounts()
    except Exception:  # noqa: BLE001
        accounts = []
    real = [a for a in accounts if not a.is_demo]
    steps.append(Step(
        "Conecta tu cuenta de Wallapop",
        "En «Cuentas»: añade tu cuenta y entra en Wallapop en la ventana que se abre (LOT Bot no guarda tu "
        "contraseña)." if not demo else "En DEMO ya tienes cuentas de prueba conectadas.",
        demo or any(a.is_connected for a in real), "Cuentas de Wallapop",
    ))

    try:
        master = app.master_ads.get(None)
    except Exception:  # noqa: BLE001
        master = None
    steps.append(Step(
        "Rellena tu anuncio principal",
        "Título, precio y descripción: LOT Bot publica exactamente esto en tus cuentas.",
        bool(master and master.title and master.price), "Anuncio principal",
    ))
    steps.append(Step(
        "Añade las fotos",
        "En «Anuncio principal», sube las fotos de tu producto (cada anuncio usa fotos distintas).",
        bool(master and master.images), "Anuncio principal",
    ))
    try:
        published = _published_count(app)
    except Exception:  # noqa: BLE001
        published = 0
    steps.append(Step(
        "Publica tu primer anuncio",
        "En «Publicación automática»: elige cuentas y copias y pulsa «Empezar». Si Wallapop pide una "
        "verificación, la completas tú y LOT Bot sigue.",
        published > 0, "Publicación automática",
    ))
    return steps


def should_show_at_start(app: Application) -> bool:
    from lot_bot.database.models import Setting

    try:
        with app.db.session_scope() as session:
            row = session.get(Setting, SETTING_KEY)
            if row is not None and (row.value or {}).get("no_mostrar"):
                return False
        return not all(step.done for step in onboarding_steps(app))
    except Exception:  # noqa: BLE001 - la guía nunca debe impedir abrir LOT Bot
        logger.exception("Primeros pasos")
        return False


def remember_choice(app: Application, hide: bool) -> None:
    from lot_bot.database.models import Setting

    with app.db.session_scope() as session:
        row = session.get(Setting, SETTING_KEY)
        if row is None:
            session.add(Setting(key=SETTING_KEY, value={"no_mostrar": hide}))
        else:
            row.value = {**(row.value or {}), "no_mostrar": hide}


class OnboardingDialog(QDialog):
    def __init__(self, app: Application, navigate: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.navigate = navigate
        self.setWindowTitle("LOT Bot · Primeros pasos")
        self.setFixedWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        title = QLabel("Primeros pasos con LOT Bot")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        steps = onboarding_steps(app)
        done = sum(1 for s in steps if s.done)
        subtitle = QLabel(
            f"{done} de {len(steps)} hechos. LOT Bot marca solo lo que ya está listo; pulsa «Ir» para "
            "hacer lo que falta."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        for number, step in enumerate(steps, 1):
            row = QFrame()
            row.setObjectName("Card")
            box = QHBoxLayout(row)
            box.setContentsMargins(14, 10, 14, 10)
            mark = QLabel("✓" if step.done else str(number))
            mark.setFixedWidth(28)
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setStyleSheet(
                f"font-weight: 700; font-size: 16px; color: {theme.SUCCESS if step.done else theme.ACCENT};"
            )
            box.addWidget(mark)
            texts = QVBoxLayout()
            texts.setSpacing(2)
            head = QLabel(step.title)
            head.setStyleSheet("font-weight: 700;")
            texts.addWidget(head)
            detail = QLabel(step.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            detail.setFixedWidth(500)
            # Alto según el ancho (si no, Qt corta la segunda línea).
            detail.setMinimumHeight(detail.heightForWidth(500) + 4)
            texts.addWidget(detail)
            box.addLayout(texts, 1)
            go = QPushButton("Hecho" if step.done else "Ir")
            go.setEnabled(not step.done)
            if not step.done:
                go.setObjectName("Primary")
            go.clicked.connect(lambda _=False, s=step: self._go(s))
            box.addWidget(go)
            layout.addWidget(row)

        self.hide_box = QCheckBox("No mostrar al abrir LOT Bot (sigue en Configuración → Acerca de)")
        layout.addWidget(self.hide_box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.finished.connect(self._save)

    def _go(self, step: Step) -> None:
        self.accept()
        self.navigate(step.section, step.tab)

    def _save(self, *_args: Any) -> None:
        try:
            if self.hide_box.isChecked():
                remember_choice(self.app, True)
        except Exception:  # noqa: BLE001
            logger.exception("No se ha podido guardar la preferencia de Primeros pasos")
