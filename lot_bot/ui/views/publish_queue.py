"""Pantalla «Publicación automática»: progreso de la cola en tiempo real."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import (
    Card,
    ProgressRing,
    SectionTitle,
    ask_confirmation,
    build_table,
    fill_table,
    selected_row_data,
    show_error,
)

STATUS_LABELS = {
    "pending": "Pendiente",
    "generating": "Generando imagen",
    "waiting": "En espera",
    "publishing": "Publicando",
    "published": "Publicado",
    "unconfirmed": "Sin confirmar",
    "failed": "Fallido",
    "cancelled": "Cancelado",
}
JOB_LABELS = {
    "pending": "Preparada",
    "running": "En marcha",
    "paused": "En pausa",
    "completed": "Terminada",
    "cancelled": "Cancelada",
}
STATUS_COLORS = {
    "unconfirmed": theme.WARNING,
    "published": theme.SUCCESS,
    "failed": theme.DANGER,
    "cancelled": theme.TEXT_MUTED,
    "waiting": theme.WARNING,
    "generating": theme.WARNING,
    "publishing": theme.WARNING,
}


class PublishQueueView(BaseView):
    title = "Publicación automática"
    subtitle = (
        "Los anuncios se publican de uno en uno o, si lo eliges, en varias cuentas a la vez, "
        "siempre con un intervalo mínimo"
    )

    def build(self) -> None:
        self.add_header_button("Actualizar", self.refresh)
        self._job_id: int | None = None

        # Arriba: anillo de progreso, qué está pasando y los botones.
        card = Card()
        hero = QHBoxLayout()
        hero.setSpacing(18)
        self.ring = ProgressRing(64, 6)
        hero.addWidget(self.ring)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.summary_title = QLabel("No hay ninguna cola")
        self.summary_title.setObjectName("HeroCaption")
        texts.addWidget(self.summary_title)
        self.hero_title = QLabel("Nada publicándose")
        self.hero_title.setObjectName("HeroTitle")
        texts.addWidget(self.hero_title)
        self.hero_text = QLabel()
        self.hero_text.setObjectName("HeroText")
        self.hero_text.setWordWrap(True)
        texts.addWidget(self.hero_text)
        hero.addLayout(texts, 1)
        self.start_button = QPushButton("Iniciar")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self._start)
        hero.addWidget(self.start_button)
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self._pause)
        hero.addWidget(self.pause_button)
        self.resume_button = QPushButton("Continuar")
        self.resume_button.setObjectName("Primary")
        self.resume_button.clicked.connect(self._resume)
        hero.addWidget(self.resume_button)
        card.body.addLayout(hero)
        self.summary = QLabel()
        self.summary.setObjectName("HeroText")
        self.summary.setWordWrap(True)
        card.add(self.summary)
        self.body.addWidget(card)

        tasks = Card()
        tasks.add(SectionTitle("Anuncios de la cola"))
        self.table = build_table(
            ["#", "Cuenta", "Anuncio", "Estado", "Inicio", "Publicado", "Resultado / error"]
        )
        tasks.add(self.table)
        row = QHBoxLayout()
        self.retry_button = QPushButton("Reintentar anuncio fallido")
        self.retry_button.clicked.connect(self._retry)
        row.addWidget(self.retry_button)
        row.addStretch(1)
        self.cancel_button = QPushButton("Cancelar cola")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.cancel_button)
        tasks.body.addLayout(row)
        self.body.addWidget(tasks, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        queue = self.app.publish_queue
        progress = queue.progress(None)
        if progress is None:
            self._job_id = None
            self.summary_title.setText("Publicación automática")
            self.hero_title.setText("No hay ninguna cola")
            self.hero_text.setText(
                "Pide en el asistente, por ejemplo, «Publica 10 canapés». Verás aquí el "
                f"progreso. Intervalo mínimo actual: {queue.interval} s."
            )
            self.summary.setText("")
            self.ring.set_progress(0, 1)
            fill_table(self.table, [])
            self._buttons(None)
            return
        self._job_id = progress.job_id
        demo = " · MODO DEMO (simulado)" if progress.is_demo else ""
        estado = JOB_LABELS.get(progress.status, progress.status)
        self.summary_title.setText(f"{progress.name} · {estado}{demo}")
        self.hero_title.setText(f"{progress.published} de {progress.total} publicados")
        ring_color = {
            "paused": theme.WARNING, "completed": theme.SUCCESS, "cancelled": theme.TEXT_FAINT,
        }.get(progress.status, theme.ACCENT)
        self.ring.set_progress(progress.published, progress.total, ring_color)
        if progress.status == "running" and progress.parallel:
            active = progress.publishing_accounts
            self.hero_text.setText(
                f"A la vez, cada cuenta con su navegador: {', '.join(active)}."
                if active
                else "A la vez, cada cuenta con su navegador."
            )
        elif progress.status == "running" and progress.next_allowed_at:
            siguiente = f"Siguiente a las {progress.next_allowed_at:%H:%M}"
            if progress.current_account:
                siguiente += f" en {progress.current_account}"
            self.hero_text.setText(siguiente + ".")
        elif progress.status == "running":
            self.hero_text.setText(f"Publicando en {progress.current_account or '…'}.")
        else:
            self.hero_text.setText(estado + ".")
        lines = [
            "Última publicación: "
            + (f"{progress.last_publish_at:%H:%M:%S}" if progress.last_publish_at else "—")
            + f" · intervalo mínimo {progress.interval_seconds} s"
            + (" por cuenta (a la vez)" if progress.parallel else "")
            + " · "
            f"{progress.in_progress} en curso · {progress.pending} pendientes · "
            f"{progress.failed} fallidos",
        ]
        verifying = [
            v for v in queue.pending_verifications() if v["cola"] == progress.job_id
        ]
        if verifying:
            names = ", ".join(v["cuenta"] for v in verifying)
            others = any(v["aplazada"] for v in verifying)
            lines.append(
                f"<b style='color:{theme.WARNING}'>Verificación de Wallapop pendiente en:</b> "
                f"{names}. Complétala en su ventana de Chrome; LOT Bot sigue solo al terminar"
                + (" (mientras tanto, publica en las demás cuentas)." if others else ".")
            )
        for note in queue.pacing_notes():
            lines.append(f"<span style='color:{theme.TEXT_MUTED}'>{note}</span>")
        if progress.status == "paused" and progress.pause_reason:
            lines.append(f"<b style='color:{theme.WARNING}'>En pausa:</b> {progress.pause_reason}")
        self.summary.setText("<br>".join(lines))
        tasks = progress.tasks
        fill_table(
            self.table,
            [
                [
                    t["posicion"],
                    t["cuenta"],
                    t["anuncio"],
                    STATUS_LABELS.get(t["estado"], t["estado"]),
                    f"{t['inicio']:%H:%M:%S}" if t["inicio"] else "",
                    f"{t['publicado']:%H:%M:%S}" if t["publicado"] else "",
                    t["error"] or t["url"] or t["id_wallapop"] or "",
                ]
                for t in tasks
            ],
            row_data=[t["id"] for t in tasks],
            colorizer=lambda row, col, _v: (
                STATUS_COLORS.get(tasks[row]["estado"]) if col == 3 and row < len(tasks) else None
            ),
        )
        self._buttons(progress)

    def _buttons(self, progress) -> None:
        status = progress.status if progress else None
        self.start_button.setEnabled(status == "pending")
        self.pause_button.setEnabled(status == "running")
        self.resume_button.setEnabled(status == "paused")
        # Solo se ve el botón que tiene sentido ahora (menos ruido).
        self.start_button.setVisible(status == "pending")
        self.pause_button.setVisible(status == "running")
        self.resume_button.setVisible(status == "paused")
        self.cancel_button.setEnabled(status in ("pending", "running", "paused"))
        self.retry_button.setEnabled(bool(progress and progress.failed))

    # ------------------------------------------------------------------
    def _safe(self, action) -> None:
        try:
            action()
        except (ValueError, RuntimeError) as exc:
            show_error(self, str(exc))
        self.refresh()

    def _start(self) -> None:
        if self._job_id:
            self._safe(lambda: self.app.publish_queue.start(self._job_id))

    def _pause(self) -> None:
        if self._job_id:
            self._safe(lambda: self.app.publish_queue.pause(self._job_id))

    def _resume(self) -> None:
        if self._job_id:
            self._safe(lambda: self.app.publish_queue.resume(self._job_id))

    def _cancel(self) -> None:
        if self._job_id and ask_confirmation(
            self,
            "Cancelar cola",
            "No se publicará nada más de esta cola. Lo ya publicado no se toca.",
            destructive=True,
        ):
            self._safe(lambda: self.app.publish_queue.cancel(self._job_id))

    def _retry(self) -> None:
        selected = selected_row_data(self.table)
        progress = self.app.publish_queue.progress(self._job_id)
        tasks = progress.tasks if progress else []
        failed = [t["id"] for t in tasks if t["estado"] == "failed"]
        unconfirmed = [t["id"] for t in tasks if t["estado"] == "unconfirmed"]
        # Uno «sin confirmar» solo si lo has elegido tú y tras avisar: pudo publicarse.
        chosen = next((t for t in selected if t in unconfirmed), None)
        if chosen is not None:
            if ask_confirmation(
                self,
                "Reintentar anuncio sin confirmar",
                "Wallapop no confirmó este anuncio: puede que YA esté publicado. Míralo en "
                "Wallapop («Tus productos») antes de reintentarlo, o tendrás un duplicado.\n\n"
                "¿Ya lo has comprobado y NO está publicado?",
                destructive=True,
            ):
                self._safe(
                    lambda: self.app.publish_queue.retry_task(chosen, allow_unconfirmed=True)
                )
            return
        target = next((t for t in selected if t in failed), failed[0] if failed else None)
        if target is not None:
            self._safe(lambda: self.app.publish_queue.retry_task(target))
