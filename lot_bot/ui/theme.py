"""Tema visual de LOT Bot: paleta e hoja de estilos Qt."""

from __future__ import annotations

import sys

# --- Paleta «E2 · noche»: grafito neutro, una sola luz cálida de acento ---
# Sin degradados ni brillos de color: superficies planas que se distinguen por
# un tono y una línea fina, como una app de escritorio de verdad.
BG = "#111216"
BG_ELEVATED = "#16171b"  # barra lateral y campos
CARD = "#17181d"
CARD_HOVER = "#1e1f24"
BORDER = "#24252b"
BORDER_STRONG = "#2e2f36"
TEXT = "#ececef"
TEXT_MUTED = "#a9aab1"
TEXT_FAINT = "#8e8f96"  # legible sobre el fondo (antes era demasiado tenue)

ACCENT = "#f5a524"
ACCENT_HOVER = "#f7b54d"
ACCENT_PRESSED = "#d98f12"
ACCENT_SOFT = "#2a2215"
ACCENT_TEXT = "#17120a"  # texto sobre el color de acento

DANGER = "#f0716a"
DANGER_HOVER = "#ff8a82"
WARNING = "#f5b547"
SUCCESS = "#5bc883"
INFO = "#6cb4ee"

#: Menú lateral (barra de iconos).
RAIL_BG = "#16171b"
RAIL_ACTIVE = "#26272d"
RAIL_TEXT = "#9c9da4"

IS_MAC = sys.platform == "darwin"
#: Tecla de los atajos tal y como se ve en el teclado: Cmd (⌘) en Mac, Ctrl en Windows.
MOD_KEY = "⌘" if IS_MAC else "Ctrl"
#: Donde se arrastran los archivos: el Finder en Mac, el Explorador en Windows.
FILE_MANAGER = "el Finder" if IS_MAC else "Windows"

FONT_FAMILY = (
    "'Segoe UI Variable Text', 'Segoe UI', '.AppleSystemUIFont', 'SF Pro Text', "
    "'Inter', 'Helvetica Neue', Arial, sans-serif"
)


def _asset(name: str) -> str:
    """Ruta de una imagen del tema, en el formato que entiende Qt (con «/»)."""
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "resources" / "ui" / name).as_posix()


def stylesheet() -> str:
    """Hoja de estilos completa de la aplicacion."""
    chevron_down = _asset("chevron-down.svg")
    chevron_up = _asset("chevron-up.svg")
    check = _asset("check.svg")
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}

QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Content {{ background: {BG}; }}
QWidget#CardContent {{ background: transparent; }}

/* ---------- Barra lateral (iconos con nombre corto) ---------- */
QFrame#Sidebar {{
    background: {RAIL_BG};
    border-right: 1px solid {BORDER};
}}
QToolButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 7px 2px 6px 2px;
    color: {RAIL_TEXT};
    font-size: 10px;
    font-weight: 500;
}}
QToolButton#NavButton:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QToolButton#NavButton:pressed {{ background: {BORDER}; padding-top: 8px; padding-bottom: 5px; }}
QToolButton#NavButton:checked {{ background: {RAIL_ACTIVE}; color: #ffffff; }}
QLabel#RailFooter {{ color: {TEXT_FAINT}; font-size: 10px; padding: 8px 0; }}
QLabel#Brand {{
    font-size: 17px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.2px;
}}
QLabel#BrandSub {{
    font-size: 10px;
    font-weight: 600;
    color: {ACCENT};
    letter-spacing: 1px;
}}
QLabel#NavSection {{
    font-size: 10px;
    font-weight: 600;
    color: {TEXT_FAINT};
    letter-spacing: 1.2px;
    padding: 14px 24px 6px 24px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 9px;
    text-align: left;
    padding: 9px 12px;
    margin: 1px 12px;
    color: {TEXT_MUTED};
    font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QPushButton#NavButton:checked {{
    background: {ACCENT_SOFT};
    color: {TEXT};
    font-weight: 600;
}}
QLabel#SidebarFooter {{ color: {TEXT_FAINT}; font-size: 11px; padding: 10px 24px; }}

/* ---------- Aviso de modo DEMO ---------- */
QLabel#DemoBanner {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    border-bottom: 1px solid #4a3a16;
    font-weight: 600;
    padding: 9px 24px;
}}

QFrame#VerificationBanner {{
    background: #2a2215;
    border-bottom: 1px solid #4a3818;
}}
QFrame#UpdateBanner {{
    background: #16202a;
    border-bottom: 1px solid #24384a;
}}
QLabel#UpdateBannerText {{ color: #cfe4f7; font-weight: 600; background: transparent; }}
QLabel#VerificationBannerText {{
    color: #f2d9ae;
    font-weight: 600;
    font-size: 13px;
    background: transparent;
}}
QFrame#VerificationBanner QPushButton {{
    background: transparent;
    border: 1px solid #5c4520;
    color: {WARNING};
    font-weight: 600;
}}
QFrame#VerificationBanner QPushButton:hover {{ background: #33291a; }}

/* ---------- Cabecera ---------- */
QLabel#PageTitle {{ font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel#PageSubtitle {{ font-size: 12px; color: {TEXT_MUTED}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; padding: 2px 0 6px 0; }}

/* ---------- Tarjetas ---------- */
QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#StatCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
/* ---------- Chat del asistente ---------- */
QLabel#ChatMeta {{ color: {TEXT_FAINT}; font-size: 11px; background: transparent; }}
QLabel#ChatAction {{
    color: {TEXT_MUTED};
    font-size: 12px;
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 3px 10px;
}}
QPushButton#ChatChip {{
    background: transparent;
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;  /* más de la mitad de la altura: Qt no redondea */
    min-height: 16px;
    padding: 4px 13px;
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QPushButton#ChatChip:hover {{ border-color: {ACCENT}; color: {TEXT}; background: {ACCENT_SOFT}; }}
QPushButton#ChatChip:pressed {{ padding-top: 5px; padding-bottom: 3px; }}
QFrame#ChatInput {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 14px;
}}
QTextEdit#ChatInputText {{
    background: transparent;
    border: none;
    padding: 4px 0;
    font-size: 13.5px;
}}

QLabel#HeroCaption {{ font-size: 12px; color: {TEXT_FAINT}; }}
QLabel#HeroTitle {{ font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel#HeroText {{ font-size: 13px; color: {TEXT_MUTED}; }}
QLabel#StatValue {{ font-size: 28px; font-weight: 700; color: {TEXT}; }}
QLabel#StatLabel {{ font-size: 10px; font-weight: 600; color: {TEXT_MUTED}; letter-spacing: 1px; }}
QLabel#StatHint {{ font-size: 11px; color: {TEXT_FAINT}; }}

/* ---------- Botones ----------
   Al pulsar, el texto baja 1 px y el fondo se oscurece: se nota el clic. */
QPushButton {{
    background: #22232a;
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 7px 15px;
    color: {TEXT};
    font-weight: 500;
}}
QPushButton:hover {{ background: #2a2b32; border-color: #3a3b43; }}
QPushButton:pressed {{ background: #1b1c21; padding-top: 8px; padding-bottom: 6px; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; background: {BG_ELEVATED}; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    border-top-color: #f8c063;  /* luz arriba: botón con relieve */
    color: {ACCENT_TEXT};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton#Primary:disabled {{ background: {BORDER}; border-color: {BORDER}; color: {TEXT_FAINT}; }}

QPushButton#Danger {{
    background: transparent;
    border: 1px solid transparent;
    color: {DANGER};
    font-weight: 500;
}}
QPushButton#Danger:hover {{ background: #2a1a1a; border-color: #4a2a2a; }}
QPushButton#Danger:pressed {{ background: #221515; padding-top: 8px; padding-bottom: 6px; }}
QPushButton#Danger:disabled {{ color: {TEXT_FAINT}; background: transparent; }}

QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER_STRONG}; }}
QPushButton#Ghost:hover {{ background: {CARD_HOVER}; }}

/* ---------- Campos ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 8px 11px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #3a3b43; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {TEXT_FAINT}; }}

/* Altura mínima del texto: en ventanas pequeñas el contenido no se corta. */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 20px; }}
QComboBox {{ padding-right: 34px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 30px;
    border: none;
}}
QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

/* Flechas de los campos numéricos: grandes y fáciles de pulsar */
QSpinBox, QDoubleSpinBox {{ padding-right: 30px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    border-left: 1px solid {BORDER_STRONG};
    border-top-right-radius: 9px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 26px;
    border: none;
    border-left: 1px solid {BORDER_STRONG};
    border-bottom-right-radius: 9px;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {CARD_HOVER}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{chevron_up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{chevron_down}"); width: 10px; height: 10px; }}

/* ---------- Tablas ---------- */
QTableWidget, QTableView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    alternate-background-color: {CARD};  /* sin rayas: separadores finos */
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {CARD};
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    padding: 9px 8px;
    color: {TEXT_FAINT};
    font-weight: 500;
    font-size: 11px;
}}
QTableWidget::item {{ padding: 8px 6px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTableCornerButton::section {{ background: {CARD}; border: none; }}

/* ---------- Listas ---------- */
QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 6px;
}}
QListWidget::item {{ padding: 9px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget::item:hover {{ background: {CARD_HOVER}; }}

/* ---------- Pestañas ---------- */
QTabWidget::pane {{ border: none; top: -1px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    padding: 9px 16px;
    margin-right: 4px;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}

/* ---------- Áreas con desplazamiento ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QDialog QScrollArea {{ background: {BG}; }}

/* ---------- Barras de desplazamiento ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3b43; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 3px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- Casillas ---------- */
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px;
    border: 1px solid #3a3b43;
    background: {BG_ELEVATED};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{check}"); }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 4px solid {BG_ELEVATED}; }}

/* ---------- Otros ---------- */
QProgressBar {{
    background: {BORDER};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QToolTip {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 6px 9px;
    color: {TEXT};
}}
QSplitter::handle {{ background: {BORDER}; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 7px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMessageBox {{ background: {BG}; }}
QStatusBar {{ background: {BG_ELEVATED}; border-top: 1px solid {BORDER}; color: {TEXT_FAINT}; font-size: 11px; }}
QStatusBar QLabel {{ color: {TEXT_FAINT}; font-size: 11px; }}
"""


#: Colores por estado, para las etiquetas de la interfaz.
STATUS_COLORS: dict[str, str] = {
    "connected": SUCCESS,
    "disconnected": TEXT_FAINT,
    "expired": WARNING,
    "error": DANGER,
    "active": SUCCESS,
    "draft": TEXT_FAINT,
    "ready": INFO,
    "published": SUCCESS,
    "paused": WARNING,
    "archived": TEXT_FAINT,
    "removed": DANGER,
    "sold": INFO,
    "ok": SUCCESS,
    "failed": DANGER,
    "running": INFO,
    "idle": TEXT_FAINT,
}
