"""Pantalla «Imágenes»: tus fotos, subidas desde el ordenador.

Solo se suben fotos (una, varias, una carpeta o arrastrándolas). Se guardan en
la carpeta de datos de LOT Bot, en este ordenador, y se pueden usar en los
anuncios. No hay generación de imágenes con IA.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)

from lot_bot.images.generation import GenerationError
from lot_bot.images.generation.prompts import OPERATIONS
from lot_bot.ui import theme
from lot_bot.ui.views.base import BaseView
from lot_bot.ui.widgets.common import Card, SectionTitle, ask_confirmation, info_box, show_error
from lot_bot.ui.widgets.images_dialog import dropped_images, image_files_in

OPERATION_NAMES = {**OPERATIONS, "propia": "Foto propia"}


def use_image_in_ads(app, path: str) -> bool:
    """Añade una imagen a las fotos del anuncio principal. True si se añadió."""
    master = app.master_ads.get(None)
    before = len(master.images)
    imported = app.images.import_image(path, "anuncio-principal", position=before)
    app.master_ads.add_images(master.key, [imported.to_dict()])
    added = len(app.master_ads.get(master.key).images) > before
    if added:
        app.audit.record_success(
            "Fotografías del anuncio principal", target=master.name, detail="1 añadida desde Imágenes"
        )
    return added


class ImageStudioView(BaseView):
    title = "Imágenes"
    subtitle = "Tus fotos, subidas desde el ordenador. Se guardan en LOT Bot"

    def build(self) -> None:
        self.add_header_button("Subir fotos…", self._upload, primary=True)
        self.add_header_button("Subir carpeta…", self._upload_folder)
        # También se pueden ARRASTRAR fotos (o una carpeta) a esta pantalla.
        self.setAcceptDrops(True)

        self.notice = QLabel(
            "Elige fotos JPG, PNG o WEBP de tu ordenador, o arrástralas aquí. Se guarda una "
            "copia en la carpeta de LOT Bot, así que puedes mover o borrar las originales."
        )
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.body.addWidget(self.notice)

        columns = QHBoxLayout()
        list_card = Card()
        list_card.add(SectionTitle("Tus fotos"))
        self.images = QListWidget()
        # Varias a la vez: arrastrar con el ratón, Ctrl/Shift + clic o Ctrl+A.
        self.images.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.images.currentItemChanged.connect(self._show_selected)
        self.images.itemSelectionChanged.connect(self._update_delete)
        list_card.add(self.images)
        list_buttons = QHBoxLayout()
        self.select_all_button = QPushButton("Seleccionar todas")
        self.select_all_button.clicked.connect(self.images.selectAll)
        list_buttons.addWidget(self.select_all_button)
        list_buttons.addStretch(1)
        self.delete_button = QPushButton("Borrar seleccionadas")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_selected)
        list_buttons.addWidget(self.delete_button)
        list_card.body.addLayout(list_buttons)
        columns.addWidget(list_card, 2)

        preview_card = Card()
        self.preview = QLabel("Selecciona una foto")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 300)
        preview_card.add(self.preview)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        preview_card.add(self.info)
        use_row = QHBoxLayout()
        use_row.addStretch(1)
        self.use_button = QPushButton("Usar en mis anuncios")
        self.use_button.setObjectName("Primary")
        self.use_button.setToolTip(
            "Añade la foto elegida a las fotos del anuncio principal: se publicará con ella."
        )
        self.use_button.clicked.connect(self._use_in_ads)
        use_row.addWidget(self.use_button)
        preview_card.body.addLayout(use_row)
        columns.addWidget(preview_card, 3)
        self.body.addLayout(columns, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        current = self._selected_id()
        self.images.clear()
        for info in self.app.image_generation.history(200):
            if not info["existe"]:
                continue
            name = Path(info["ruta"]).name
            label = f"{name} · {info['fecha']:%d/%m %H:%M}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, info)
            self.images.addItem(item)
            if info["id"] == current:
                self.images.setCurrentItem(item)
        if not self.images.count():
            self.preview.setText("Aún no has subido ninguna foto.\nPulsa «Subir fotos…» o arrástralas aquí.")
        self._show_selected()
        self._update_delete()

    def _selected(self) -> dict | None:
        item = self.images.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected_ids(self) -> list[int]:
        return [i.data(Qt.ItemDataRole.UserRole)["id"] for i in self.images.selectedItems()]

    def _update_delete(self) -> None:
        count = len(self.images.selectedItems())
        self.delete_button.setEnabled(count > 0)
        self.delete_button.setText(
            f"Borrar seleccionadas ({count})" if count else "Borrar seleccionadas"
        )

    def _delete_selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        if not ask_confirmation(
            self,
            "Borrar imágenes",
            f"Se borrarán {len(ids)} imagen(es) de esta lista.\n\n"
            "Las fotos originales de tu ordenador NO se borran, y las que ya usas en tus "
            "anuncios siguen allí.",
            destructive=True,
        ):
            return
        removed = self.app.image_generation.delete_images(ids)
        self.app.audit.record_success("Imágenes borradas", detail=f"{removed} imagen(es)")
        self.refresh()

    def _selected_id(self) -> int | None:
        info = self._selected() if hasattr(self, "images") else None
        return info["id"] if info else None

    def _show_selected(self, *_):
        info = self._selected()
        if hasattr(self, "use_button"):
            self.use_button.setEnabled(info is not None)
        if info is None:
            if self.images.count():
                self.preview.setText("Selecciona una foto")
            self.preview.setPixmap(QPixmap())
            self.info.setText("")
            return
        pixmap = QPixmap(info["ruta"])
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.width(),
                    self.preview.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        origin = "Foto propia" if info["operacion"] == "propia" else OPERATION_NAMES.get(
            info["operacion"], info["operacion"]
        )
        self.info.setText(f"{Path(info['ruta']).name} · {origin} · {info['fecha']:%d/%m/%Y %H:%M}")

    # ------------------------------------------------------------------
    def _use_in_ads(self) -> None:
        info = self._selected()
        if info is None:
            return
        try:
            added = use_image_in_ads(self.app, info["ruta"])
        except Exception as exc:
            show_error(self, "No se ha podido añadir la foto.", str(exc))
            return
        if added:
            info_box(
                self,
                "Foto añadida",
                "La imagen se usará en tus anuncios (Anuncio principal → Fotografías).",
            )
        else:
            info_box(self, "Ya estaba", "Esa imagen ya está entre las fotos de tus anuncios.")

    def _upload(self) -> None:
        # Varias a la vez: Ctrl/Shift + clic, o Ctrl+A para toda la carpeta.
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Subir fotos (puedes elegir varias)", "",
            "Imágenes (*.jpg *.jpeg *.png *.webp)",
        )
        self.upload_paths(paths)

    def _upload_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Elige la carpeta con las fotos")
        if not folder:
            return
        paths = image_files_in(folder)
        if not paths:
            info_box(self, "Fotos propias", "En esa carpeta no hay fotos JPG, PNG ni WEBP.")
            return
        self.upload_paths(paths)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt)
        if dropped_images(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt)
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt)
        paths = dropped_images(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.upload_paths(paths)

    def upload_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        use = ask_confirmation(
            self,
            "Usar en mis anuncios",
            f"Has elegido {len(paths)} foto(s). ¿Quieres usarlas también en tus anuncios "
            f"(Anuncio principal → Fotografías)?",
        )
        saved, used, problems = self.upload_files(paths, use_in_ads=use)
        message = f"{saved} foto(s) guardadas."
        if use:
            message += f" {used} añadidas a tus anuncios."
        if problems:
            message += "\n\nNo se han podido añadir:\n" + "\n".join(f"• {p}" for p in problems)
        info_box(self, "Fotos propias", message)
        self.refresh()

    def upload_files(self, paths: list[str], *, use_in_ads: bool) -> tuple[int, int, list[str]]:
        """Guarda cada foto (y, si se pide, la añade a los anuncios). Una foto
        que falla no impide subir las demás."""
        saved = used = 0
        problems: list[str] = []
        for path in paths:
            name = Path(path).name
            try:
                result = self.app.image_generation.add_own_image(Path(path))
            except GenerationError as exc:
                problems.append(f"{name}: {exc.user_message}")
                continue
            except Exception as exc:
                problems.append(f"{name}: no es una imagen válida ({type(exc).__name__})")
                continue
            saved += 1
            self.app.audit.record_success("Foto propia añadida", detail=f"imagen {result.image_id}")
            if use_in_ads:
                try:
                    if use_image_in_ads(self.app, str(result.path)):
                        used += 1
                except Exception as exc:
                    problems.append(f"{name}: no se ha podido añadir a los anuncios ({exc})")
        return saved, used, problems
