"""ModBridge GUI (PySide6): search, import, and profile transfer for Minecraft mods."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def _chevron_icon_url() -> str:
    """Light chevron for QComboBox::down-arrow as a QSS url.

    The native arrow uses OS palette colors and vanishes on the dark
    theme (and can't be intercepted via QProxyStyle). A theme-colored
    PNG looks the same everywhere. Loaded from assets/, with temp-dir
    generation as fallback; '' keeps the native arrow.
    """
    name = f"chev_{COLORS['text'].lstrip('#')}.png"
    url = _asset_url(name)
    if url:
        return url
    try:
        import tempfile
        color = COLORS["text"].lstrip("#")
        d = Path(tempfile.gettempdir()) / "ModBridge"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"chev_{color}.png"
        if not p.exists():
            px = QPixmap(14, 14)
            px.fill(Qt.transparent)
            pt = QPainter(px)
            pt.setRenderHint(QPainter.Antialiasing, True)
            pt.setPen(QPen(QColor(COLORS["text"]), 2,
                           Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pt.drawLine(3, 5, 7, 9)
            pt.drawLine(7, 9, 11, 5)
            pt.end()
            if not px.save(str(p)):
                return ""
        return "url(" + p.as_posix() + ")"
    except Exception as e:
        logger.debug("Failed to create chevron: %s", e)
        return ""


def _check_icon_url() -> str:
    """Checkmark for QCheckBox::indicator:checked as a QSS url.

    QSS can only fill the indicator; the mark itself must be an image.
    A dark mark on the accent fill is font-independent. Loaded from
    assets/, with temp-dir generation as fallback; '' keeps the fill.
    """
    name = f"check_{COLORS['bg'].lstrip('#')}.png"
    url = _asset_url(name)
    if url:
        return url
    try:
        import tempfile
        color = COLORS["bg"].lstrip("#")
        d = Path(tempfile.gettempdir()) / "ModBridge"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"check_{color}.png"
        if not p.exists():
            px = QPixmap(14, 14)
            px.fill(Qt.transparent)
            pt = QPainter(px)
            pt.setRenderHint(QPainter.Antialiasing, True)
            pt.setPen(QPen(QColor(COLORS["bg"]), 3,
                           Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pt.drawLine(3, 7.5, 6.5, 11)
            pt.drawLine(6.5, 11, 11.5, 3.5)
            pt.end()
            if not px.save(str(p)):
                return ""
        return "url(" + p.as_posix() + ")"
    except Exception as e:
        logger.debug("Failed to create checkmark: %s", e)
        return ""


_GLYPH_CACHE: dict = {}


def glyph_pixmap(filename: str, paint_fn) -> "QPixmap":
    """UI glyph: loaded from assets/, painted in memory as fallback.

    Text/emoji glyphs depend on OS fonts; a drawn PNG renders
    everywhere. Results are memoized.
    """
    from PySide6.QtGui import QPixmap as _Px
    px = _GLYPH_CACHE.get(filename)
    if px is None or px.isNull():
        asset = resource_path("assets", filename)
        px = _Px(str(asset)) if asset.exists() else None
        if px is None or px.isNull():
            logger.debug("Asset %s unavailable, painting in memory", filename)
            px = paint_fn()
        _GLYPH_CACHE[filename] = px
    return px


def cross_pixmap() -> "QPixmap":
    """Red cross for delete buttons (2x for HiDPI)."""
    return glyph_pixmap(f"cross_{COLORS['error_fg'].lstrip('#')}.png", _paint_cross)


def globe_pixmap() -> "QPixmap":
    """Globe for the language selector (2x for HiDPI)."""
    return glyph_pixmap(f"globe_{COLORS['muted'].lstrip('#')}.png", _paint_globe)


def refresh_pixmap() -> "QPixmap":
    """Refresh arrow for the profiles button (2x for HiDPI)."""
    return glyph_pixmap(f"refresh_{COLORS['accent'].lstrip('#')}.png", _paint_refresh)


def _asset_url(filename: str) -> str:
    """QSS url for an assets/ image, or '' when missing."""
    try:
        p = resource_path("assets", filename)
        if p.exists():
            return "url(" + p.as_posix() + ")"
    except Exception as e:
        logger.debug("Asset %s unavailable: %s", filename, e)
    return ""


def _paint_cross():
    """In-memory cross fallback (assets/cross_*.png missing)."""
    from PySide6.QtGui import QPixmap as _Px
    s = 32
    px = _Px(s, s)
    px.fill(Qt.transparent)
    pt = QPainter(px)
    pt.setRenderHint(QPainter.Antialiasing, True)
    pt.setPen(QPen(QColor(COLORS["error_fg"]), 3.5,
                   Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    m = 8
    pt.drawLine(m, m, s - m, s - m)
    pt.drawLine(s - m, m, m, s - m)
    pt.end()
    return px


def _paint_globe():
    """In-memory globe fallback (assets/globe_*.png missing)."""
    from PySide6.QtGui import QPixmap as _Px
    s = 36
    px = _Px(s, s)
    px.fill(Qt.transparent)
    pt = QPainter(px)
    pt.setRenderHint(QPainter.Antialiasing, True)
    pt.setPen(QPen(QColor(COLORS["muted"]), 3,
                   Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pt.drawEllipse(3, 3, 30, 30)  # outline + meridian + equator + parallels
    pt.drawEllipse(11, 3, 14, 30)
    pt.drawLine(3, 18, 33, 18)
    pt.drawLine(5.3, 10, 30.7, 10)
    pt.drawLine(5.3, 26, 30.7, 26)
    pt.end()
    return px


def _paint_refresh():
    """In-memory refresh-arrow fallback (assets/refresh_*.png missing)."""
    from PySide6.QtGui import QPixmap as _Px
    s = 36
    px = _Px(s, s)
    px.fill(Qt.transparent)
    pt = QPainter(px)
    pt.setRenderHint(QPainter.Antialiasing, True)
    pt.setPen(QPen(QColor(COLORS["accent"]), 3.5,
                   Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pt.drawArc(6, 6, 24, 24, 50 * 16, -300 * 16)  # 300° arc, gap on top
    pt.drawLine(14, 7, 6, 5.5)  # arrowhead
    pt.drawLine(14, 7, 8.5, 12.5)
    pt.end()
    return px

from .api import (
    ModrinthAPI,
    STATUS_FOUND, STATUS_NO_VERSION, STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND, STATUS_AUTHOR_MISMATCH,
)
from .resolver import ModResolver
from .localization import t as _t, SUPPORTED_LANGUAGES, DEFAULT_LANG
from ._version import __version__
from .constants import (
    COLORS, PROFILE_TRANSFER_HIDE_NAMES, PROFILE_TRANSFER_HIDE_PREFIXES,
    PROFILE_TRANSFER_DEFAULT_CHECKED, UI_FONT, MONO_FONT, FONTS,
)
from .utils import (
    fetch_minecraft_release_versions_ordered,
    get_modrinth_profiles_path,
    open_folder,
    sanitize_filename,
    sanitize_version_text,
    download_url_to_file,
    resolve_config_file,
    resolve_writable_base,
)
from .services import (
    TransferService,
    SearchCheckService,
    ImportScanService,
    TransferCallbacks,
    TransferProgress,
    TransferSummary,
    SingleResultStatus,
    BackupManager,
    ImportCallbacks,
    ImportProgress,
    ImportSummary,
    ImportItemStatus,
)
from .services.backup import (
    DEFAULT_POLICY,
    BACKUP_FULL,
    BACKUP_INTERSECTION,
    BACKUP_SKIP,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# -- worker-to-GUI signal bridges (queued across threads) -- #

class BusSignals(QObject):
    """Generic bridge for background tasks."""
    progress = Signal(object, object)  # (payload, percent); payload: *Progress | str
    done = Signal(object)  # summary object
    info = Signal(str, str)  # (kind, text), spare notifications


class IconSignals(QObject):
    loaded = Signal(object, object)  # (QLabel, {"url": str, "img": QImage})
    failed = Signal(object)          # QLabel


class ListSignals(QObject):
    versions_loaded = Signal(list)
    versions_failed = Signal(str)
    profiles_loaded = Signal(object)  # (profiles, keep_src, keep_dst, silent)
    rollback_done = Signal(bool)


# -- small helpers -- #

def _qfont(spec, fallback_size: int = 12) -> QFont:
    """Convert a FONTS tuple (family, size[, style]) to QFont."""
    try:
        family = spec[0] if len(spec) > 0 else UI_FONT
        size = int(spec[1]) if len(spec) > 1 else fallback_size
        extra = spec[2:] if len(spec) > 2 else ()
    except Exception:
        return QFont(UI_FONT, fallback_size)
    f = QFont(family, size)
    styles = " ".join(str(s).lower() for s in extra)
    if "bold" in styles:
        f.setBold(True)
    if "italic" in styles:
        f.setItalic(True)
    return f


def _mono_font(size: int = 11) -> QFont:
    return QFont(MONO_FONT, size)


def _clear_layout(layout) -> None:
    """Remove widgets but keep the trailing stretch.

    takeAt() also carries away the addStretch(1) spacer; without it the
    layout spreads spare space across the cards instead of packing them
    on top. All list layouts are [cards..., stretch], so re-adding one
    restores the invariant.
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
    layout.addStretch(1)


# -- main window -- #

class App(QMainWindow):
    IMAGE_CACHE_LIMIT = 200

    def __init__(self):
        super().__init__()

        if getattr(sys, 'frozen', False):
            self.app_path = Path(sys.executable).parent
        else:
            self.app_path = Path(__file__).parent.parent
        self.config_file = resolve_config_file(self.app_path, "config.json")
        self.downloads_base = resolve_writable_base(self.app_path)

        self.lang = self._load_language_early()
        self._qt_translator = None
        self._install_qt_translator(self.lang)

        self.api = ModrinthAPI(lang=self.lang)
        self.resolver = ModResolver(self.api)
        self.transfer_service = TransferService(self.api, self.resolver, max_workers=8)
        # Search check runs on 4 workers, not 8: each mod pulls a
        # search → project → team → versions chain, and 8 parallel
        # chains routinely hit Modrinth 429s.
        self.search_check_service = SearchCheckService(self.api, self.resolver, max_workers=4)
        self.backup_manager = BackupManager()
        self.import_scan_service = ImportScanService(self.api, max_workers=8)

        self.found_mods: list = []
        self.image_cache: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._image_lock = threading.Lock()
        self._icon_inflight: set = set()
        self._mc_release_versions_cache = None
        self._mc_versions_loaded = False
        self._last_backup_dir: Optional[Path] = None
        self._pending_transfer_new_files: Dict[str, List[str]] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._cancel_event: Optional[threading.Event] = None
        self._transfer_busy = False
        self._current_stage = "setup"
        self.available_items: Dict[str, dict] = {}
        self.profiles_path: Optional[Path] = get_modrinth_profiles_path()
        self._mc_version_values: List[str] = []

        self._icons = IconSignals()
        self._icons.loaded.connect(self._on_icon_loaded)
        self._icons.failed.connect(self._on_icon_failed)
        self._lists = ListSignals()
        self._lists.versions_loaded.connect(self._on_mc_versions_loaded)
        self._lists.versions_failed.connect(self._on_mc_versions_failed)
        self._lists.profiles_loaded.connect(self._on_profiles_loaded)
        self._lists.rollback_done.connect(self._on_rollback_done)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_settings)

        self._setup_window()
        self._build_ui()
        self._apply_styles()
        self._start_mc_versions_load()
        self.load_settings()
        self.refresh_profiles(silent=True)

    # -- localization -- #

    def tr(self, key: str, **kwargs) -> str:
        return _t(key, self.lang, **kwargs)

    def _load_language_early(self) -> str:
        try:
            if self.config_file.exists():
                data = json.loads(self.config_file.read_text(encoding='utf-8'))
                lang = str(data.get('lang', DEFAULT_LANG)).lower()
                if lang in SUPPORTED_LANGUAGES:
                    return lang
        except Exception as e:
            logger.debug("Failed to read language from config: %s", e)
        return DEFAULT_LANG

    def profile_placeholder(self) -> str:
        return self.tr('select_profile')

    def no_profiles_text(self) -> str:
        return self.tr('no_profiles')

    def on_language_change(self, label: str):
        inv = {v.lower(): k for k, v in SUPPORTED_LANGUAGES.items()}
        lang = inv.get(str(label).lower(), DEFAULT_LANG)
        if lang == self.lang:
            return
        self.lang = lang
        self.api.set_lang(lang)
        self._install_qt_translator(lang)
        self.save_settings()
        self.apply_language()

    def _install_qt_translator(self, lang: str):
        """Install Qt's own qtbase_<lang>.qm (translates standard dialog
        buttons like OK/Cancel/Yes/No; our locales/ strings are untouched)."""
        try:
            from PySide6.QtCore import QLibraryInfo, QTranslator
            app = QApplication.instance()
            old = self._qt_translator
            if old is not None:
                if app is not None:
                    app.removeTranslator(old)
                self._qt_translator = None
            tr = QTranslator(self)
            if tr.load(f"qtbase_{lang}",
                       QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
                if app is not None:
                    app.installTranslator(tr)
                self._qt_translator = tr
            else:
                logger.debug("No qtbase translation for %r", lang)
        except Exception as e:
            logger.debug("Qt translator failed: %s", e)

    def _make_native_box(self, icon, title: str, text: str,
                         buttons=QMessageBox.Ok,
                         default=QMessageBox.NoButton) -> QMessageBox:
        """Parentless (hence QSS-free) native dialog, centered over the window.

        The app stylesheet hangs on the main window and would cascade
        into child message boxes, bleaching them. Without a parent the
        dialog renders with the OS style.
        """
        box = QMessageBox(icon, title, text, buttons, None)
        if default != QMessageBox.NoButton:
            box.setDefaultButton(default)
        hint = box.sizeHint()
        c = self.geometry().center() - QPoint(hint.width() // 2, hint.height() // 2)
        box.move(max(c.x(), 0), max(c.y(), 0))
        box.setWindowModality(Qt.ApplicationModal)
        return box

    def _ask(self, icon, title: str, text: str,
             buttons=QMessageBox.Ok | QMessageBox.Cancel,
             default=QMessageBox.Cancel):
        """Native question; returns a QMessageBox.StandardButton."""
        return QMessageBox.StandardButton(
            self._make_native_box(icon, title, text, buttons, default).exec())

    def _tell(self, icon, title: str, text: str):
        """Native single-OK notification."""
        self._make_native_box(icon, title, text, QMessageBox.Ok,
                              QMessageBox.Ok).exec()

    def apply_language(self):
        """Retranslate every static widget (language switch)."""
        self.main_tabs.setTabText(0, self.tr("tab_search"))
        self.main_tabs.setTabText(1, self.tr("tab_transfer"))
        self.btn_tab_ok.setText(self.tr("tab_available"))
        self.btn_tab_err.setText(self.tr("tab_not_found"))
        self.analysis_tabs.setTabText(0, self.tr("tab_available"))
        self.analysis_tabs.setTabText(1, self.tr("tab_not_found"))
        self.lbl_version.setText(self.tr("version"))
        self.lbl_loader.setText(self.tr("loader"))
        self.btn_open_folder.setText(self.tr("app_folder"))
        idx = self.lang_combo.findData(self.lang)
        if idx >= 0:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.blockSignals(False)
        self.lbl_mods_list.setText(self.tr("mods_list"))
        self.btn_download.setText(self.tr("download_mods"))
        self.btn_check.setText(self.tr("check_list"))
        self.btn_cancel_search.setText(self.tr("cancel"))
        self.btn_open_import.setText(self.tr("import_open"))
        self.btn_open_import.setToolTip(self.tr("import_title"))
        self.btn_import_back.setText(self.tr("back"))
        self.lbl_import_title.setText(self.tr("import_title"))
        self.lbl_import_info.setText(self.tr("import_info"))
        self.btn_select_dir.setText(self.tr("select_mods_folder"))
        self.lbl_log_title.setText(self.tr("log"))
        self.lbl_transfer_header.setText(self.tr("transfer_header"))
        self.lbl_step1.setText(self.tr("step1"))
        self.lbl_step2.setText(self.tr("step2"))
        self.btn_select_profiles_dir.setText(self.tr("select_folder"))
        self.btn_refresh.setToolTip(self.tr("refresh_tip"))
        self.lbl_from.setText(self.tr("from_src"))
        self.lbl_to.setText(self.tr("to_dst"))
        self.transfer_title.setText(self.tr("what_to_transfer"))
        self.btn_next.setText(self.tr("next"))
        self.lbl_catalog_path.setText(self.tr(
            "catalog",
            path=str(self.profiles_path) if self.profiles_path else self.tr("catalog_undefined"),
        ))
        self.btn_back.setText(self.tr("back"))
        if not self._transfer_busy:
            self.btn_rollback.setText(self.tr("rollback"))
        self.lbl_analysis_result.setText(self.tr("analysis_result"))
        self.btn_cancel_transfer.setText(self.tr("cancel"))
        # Profile combos: only item 0 is a service entry (placeholder or
        # "no profiles"); profile names are user data and stay untouched.
        for combo in (self.src_combo, self.dst_combo):
            if combo.count() and combo.itemData(0) is None:
                current_data = combo.currentData()
                if current_data is None:
                    if combo.count() == 1:
                        combo.setItemText(0, self.no_profiles_text())
                    else:
                        combo.setItemText(0, self.profile_placeholder())
                else:
                    if combo.count() > 1:
                        combo.setItemText(0, self.profile_placeholder())
        descriptions = self._transfer_descriptions()
        for name, info in self.available_items.items():
            info["desc"] = descriptions.get(name, "")
            cb: QCheckBox = info.get("checkbox")
            if cb is not None:
                prefix = "📂 " if info.get("type") == "dir" else "📄 "
                desc = info["desc"]
                cb.setText(f"{prefix}{name} → {desc}" if desc else f"{prefix}{name}")
        self.set_status(self.tr("idle"), "muted")

    # -- window & styles -- #

    def _setup_window(self):
        self.setWindowTitle(f"ModBridge {__version__}")
        self.setWindowIcon(app_icon())  # title bar + taskbar
        self.resize(1140, 880)
        self.setMinimumSize(1040, 720)
        self._dark_title_applied = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._dark_title_applied:
            self._dark_title_applied = True
            self._apply_dark_titlebar()

    def _apply_dark_titlebar(self):
        """Theme-colored native title bar (Windows only).

        The frame stays native (snap, shadows, menu, resize keep
        working): caption color on Windows 11, immersive dark mode on
        10. Silently does nothing elsewhere or on any error.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            if not hwnd:
                return
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [
                ctypes.c_void_p, ctypes.c_uint,
                ctypes.c_void_p, ctypes.c_uint,
            ]
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long

            bg = COLORS["bg"].lstrip("#")
            r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
            caption = ctypes.c_int(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption),
                                      ctypes.sizeof(caption))  # Win11 only; ignored elsewhere

            dark = ctypes.c_int(1)
            for attr in (20, 19):  # 20H1+, fallback 19H1
                if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark),
                                             ctypes.sizeof(dark)) == 0:
                    break
        except Exception as e:
            logger.debug("Dark titlebar failed: %s", e)

    def _apply_styles(self):
        c = COLORS
        chev = _chevron_icon_url()
        arrow_rule = (
            f"QComboBox::down-arrow {{ image: {chev}; width: 14px; height: 14px; }}"
            if chev else ""
        )
        check = _check_icon_url()
        check_rule = (
            f"QCheckBox::indicator:checked {{ image: {check}; }}"
            if check else ""
        )
        self.setStyleSheet(f"""
        QMainWindow, QWidget#central {{ background: {c['bg']}; color: {c['text']}; }}
        QFrame#card {{
            background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px;
        }}
        QFrame#topcard {{
            background: {c['card']}; border: 1px solid {c['border']}; border-radius: 16px;
        }}
        QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 12px;
            background: {c['panel']}; top: -1px; }}
        QTabBar::tab {{
            background: {c['tab_idle']}; color: {c['text']};
            padding: 8px 18px; margin: 6px 4px 0 4px; border-top-left-radius: 8px;
            border-top-right-radius: 8px; border: 1px solid {c['border']};
        }}
        QTabBar::tab:selected {{ background: {c['accent']}; color: {c['bg']}; font-weight: bold; }}
        QTabBar::tab:!selected:hover {{ background: {c['tab_idle_hover']}; }}
        QLabel {{ color: {c['text']}; background: transparent; }}
        QLabel#muted {{ color: {c['muted']}; }}
        QLabel#accent {{ color: {c['accent']}; }}
        QLabel#error {{ color: {c['error_fg']}; }}
        QTabWidget > QWidget {{ background: transparent; }}
        QScrollArea QWidget {{ background: transparent; }}
        QPlainTextEdit, QTextEdit {{
            background: {c['input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: 8px;
            selection-background-color: {c['accent']}; selection-color: {c['bg']};
        }}
        QComboBox {{
            background: {c['input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 10px; min-height: 22px;
        }}
        QComboBox:editable {{ background: {c['input']}; }}
        QComboBox QLineEdit {{
            background: transparent; border: none; color: {c['text']};
            selection-background-color: {c['accent']}; selection-color: {c['bg']};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 32px; margin: 2px;
            border: none; border-left: 1px solid {c['border']};
            border-top-right-radius: 6px; border-bottom-right-radius: 6px;
            background: {c['tab_idle']};
        }}
        QComboBox::drop-down:hover {{ background: {c['tab_idle_hover']}; }}
        {arrow_rule}
        QComboBox QAbstractItemView {{
            background: {c['card']}; color: {c['text']};
            border: 1px solid {c['border']}; padding: 4px; outline: 0;
            selection-background-color: {c['tab_idle_hover']};
        }}
        QComboBox QAbstractItemView::item {{
            padding: 6px 10px; min-height: 22px; border-radius: 4px;
        }}
        QComboBox QAbstractItemView::item:selected {{ background: {c['tab_idle_hover']}; }}
        QPushButton {{
            border-radius: 8px; padding: 8px 14px; font-weight: bold;
            background: {c['tab_idle']}; color: {c['text']}; border: 1px solid {c['border']};
        }}
        QPushButton:hover {{ background: {c['tab_idle_hover']}; }}
        QPushButton:disabled {{ background: {c['btn_disabled']}; color: {c['muted']}; border: 1px solid {c['border']}; }}
        QPushButton#primary {{ background: {c['accent']}; color: {c['bg']}; border: none; }}
        QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
        QPushButton#primary:disabled {{ background: {c['btn_disabled']}; color: {c['muted']}; }}
        QPushButton#danger {{
            color: {c['error_fg']}; background: transparent;
            border: 1px solid {c['border']};
        }}
        QPushButton#danger:hover {{ background: {c['error']}; border: 1px solid {c['border']}; }}
        QPushButton#danger:disabled {{ color: {c['muted']}; }}
        QPushButton#delbtn {{
            background: {c['tab_idle']}; border: 1px solid {c['border']};
            border-radius: 6px;
        }}
        QPushButton#delbtn:hover {{ background: {c['error']}; border: 1px solid {c['border']}; }}
        QPushButton#ghost {{
            background: {c['accent_subtle']}; color: {c['accent']};
            border: 1px solid {c['border']};
        }}
        QPushButton#ghost:hover {{ background: {c['tab_idle_hover']}; color: {c['accent']}; }}
        QPushButton:checked {{
            background: {c['accent']}; color: {c['bg']};
            border: 1px solid {c['accent']};
        }}
        QPushButton:checked:hover {{ background: {c['accent_hover']}; }}
        QPushButton:checked:disabled {{
            background: {c['btn_disabled']}; color: {c['muted']};
            border: 1px solid {c['border']};
        }}
        QProgressBar {{
            background: {c['progress_bg']}; border: none; border-radius: 4px;
            height: 8px; text-align: center;
        }}
        QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 12px; }}
        QScrollBar:horizontal {{ background: transparent; height: 12px; }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {c['border']}; border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{ min-height: 30px; margin: 0 2px; }}
        QScrollBar::handle:horizontal {{ min-width: 30px; margin: 2px 0; }}
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
            background: {c['muted']};
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            height: 0; width: 0; background: transparent;
        }}
        QCheckBox {{ color: {c['text']}; spacing: 8px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px;
            border: 1px solid {c['border']}; background: {c['input']}; }}
        QCheckBox::indicator:checked {{ background: {c['accent']}; }}
        {check_rule}
        QSplitter::handle:horizontal {{ background: transparent; width: 16px; }}
        QSplitter::handle:horizontal:hover {{ background: {c['accent_subtle']}; }}
        QSplitter::handle:vertical {{ background: transparent; height: 16px; }}
        QFrame#card-ok {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QFrame#card-err {{ background: {c['error']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QFrame#card-warn {{ background: {c['warning']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        QFrame#card-info {{ background: {c['info']}; border: 1px solid {c['border']}; border-radius: 8px; }}
        """)

    # -- UI construction -- #

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 10)
        root.setSpacing(12)

        root.addWidget(self._build_top_panel())

        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(self._build_search_tab(), self.tr("tab_search"))
        self.main_tabs.addTab(self._build_transfer_tab(), self.tr("tab_transfer"))
        root.addWidget(self.main_tabs, 1)

        root.addLayout(self._build_bottom_panel())

    def _build_top_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("topcard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        self.lbl_version = QLabel(self.tr("version"))
        self.lbl_version.setFont(_qfont(FONTS["section"]))
        lay.addWidget(self.lbl_version)

        self.cmb_version = QComboBox()
        self.cmb_version.setEditable(True)
        self.cmb_version.setMinimumWidth(140)
        self.cmb_version.addItem(self.tr("loading"))
        self.cmb_version.currentTextChanged.connect(lambda _t: self.delayed_save())
        lay.addWidget(self.cmb_version)

        self.lbl_loader = QLabel(self.tr("loader"))
        self.lbl_loader.setFont(_qfont(FONTS["section"]))
        lay.addWidget(self.lbl_loader)

        self.cmb_loader = QComboBox()
        self.cmb_loader.addItems(["fabric", "forge", "neoforge", "quilt"])
        self.cmb_loader.setMinimumWidth(130)
        self.cmb_loader.currentTextChanged.connect(lambda _t: self.delayed_save())
        lay.addWidget(self.cmb_loader)

        self.btn_open_folder = QPushButton(self.tr("app_folder"))
        self.btn_open_folder.setObjectName("ghost")
        self.btn_open_folder.clicked.connect(self.open_app_folder)
        lay.addWidget(self.btn_open_folder)

        self.lbl_save_notify = QLabel("")
        self.lbl_save_notify.setObjectName("accent")
        self.lbl_save_notify.setFont(_qfont(FONTS["small"]))
        lay.addWidget(self.lbl_save_notify)
        lay.addStretch(1)

        self.lbl_lang_icon = QLabel()
        self.lbl_lang_icon.setPixmap(
            globe_pixmap().scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(self.lbl_lang_icon)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("RU", "ru")
        self.lang_combo.addItem("EN", "en")
        _fm = self.lang_combo.fontMetrics()
        self.lang_combo.setFixedWidth(_fm.horizontalAdvance("EN") + 58)
        idx = self.lang_combo.findData(self.lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentTextChanged.connect(self.on_language_change)
        lay.addWidget(self.lang_combo)
        return card

    def _build_bottom_panel(self):
        lay = QVBoxLayout()
        lay.setSpacing(4)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        row.addWidget(self.progress, 1)
        self.lbl_progress_percent = QLabel("0%")
        self.lbl_progress_percent.setObjectName("muted")
        self.lbl_progress_percent.setFont(_qfont(FONTS["small"]))
        self.lbl_progress_percent.setFixedWidth(44)
        row.addWidget(self.lbl_progress_percent)
        lay.addLayout(row)
        self.lbl_status = QLabel(self.tr("idle"))
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setFont(_qfont(FONTS["small"]))
        self.lbl_status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_status)
        return lay

    # -- Search tab -- #

    def _make_scroll_list(self):
        """Scrollable card list. Returns (scroll_area, inner_layout)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addStretch(1)
        scroll.setWidget(inner)
        return scroll, layout

    def _scroll_to_bottom(self, scroll: QScrollArea):
        def _go():
            try:
                # Re-run layout: the first pass sometimes measures wordWrap
                # heightForWidth at a narrow width (blowing cards up to full
                # scroll height); a second pass settles it.
                inner = scroll.widget()
                if inner is not None and inner.layout() is not None:
                    inner.layout().invalidate()
                    inner.layout().activate()
            except Exception as e:
                logger.debug("Failed to re-layout list: %s", e)
            try:
                bar = scroll.verticalScrollBar()
                bar.setValue(bar.maximum())
            except Exception as e:
                logger.debug("Failed to scroll down: %s", e)
        QTimer.singleShot(1, _go)

    def _build_search_tab(self) -> QWidget:
        """Search tab: QStackedWidget (search | import with a Back button)."""
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search_stack = QStackedWidget()
        self.search_stack.addWidget(self._build_search_page())
        self.search_stack.addWidget(self._build_import_page())
        lay.addWidget(self.search_stack)
        return root

    def _build_search_page(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        splitter = QSplitter(Qt.Horizontal)

        # Left card: mod list.
        left = QFrame()
        left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        self.lbl_mods_list = QLabel(self.tr("mods_list"))
        self.lbl_mods_list.setFont(_qfont(FONTS["head"]))
        left_lay.addWidget(self.lbl_mods_list)
        self.txt_mods = QPlainTextEdit()
        self.txt_mods.setFont(_mono_font(11))
        self.txt_mods.setPlaceholderText("Sodium\nIris Shaders\n...")
        self.txt_mods.textChanged.connect(self.delayed_save)
        left_lay.addWidget(self.txt_mods, 1)
        self.btn_open_import = QPushButton(self.tr("import_open"))
        self.btn_open_import.setObjectName("ghost")
        self.btn_open_import.setToolTip(self.tr("import_title"))
        self.btn_open_import.clicked.connect(
            lambda: self.search_stack.setCurrentIndex(1))
        left_lay.addWidget(self.btn_open_import)
        splitter.addWidget(left)

        # Right side: actions + results.
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)
        btn_row = QHBoxLayout()
        self.btn_check = QPushButton(self.tr("check_list"))
        # Gray on purpose: green is reserved for "Download mods".
        self.btn_check.clicked.connect(self.start_check)
        btn_row.addWidget(self.btn_check)
        self.btn_download = QPushButton(self.tr("download_mods"))
        self.btn_download.setObjectName("primary")
        self.btn_download.setEnabled(False)
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self.start_download)
        btn_row.addWidget(self.btn_download)
        self.btn_cancel_search = QPushButton(self.tr("cancel"))
        self.btn_cancel_search.setObjectName("danger")
        self.btn_cancel_search.setVisible(False)
        self.btn_cancel_search.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel_search)
        btn_row.addStretch(1)
        # Available/Not-found switch: plain buttons in the same row, right side.
        self.btn_tab_ok = QPushButton(self.tr("tab_available"))
        self.btn_tab_ok.setCheckable(True)
        self.btn_tab_ok.setChecked(True)
        self.btn_tab_err = QPushButton(self.tr("tab_not_found"))
        self.btn_tab_err.setCheckable(True)
        self.results_group = QButtonGroup(self)
        self.results_group.setExclusive(True)
        self.results_group.addButton(self.btn_tab_ok, 0)
        self.results_group.addButton(self.btn_tab_err, 1)
        self.results_group.idClicked.connect(
            lambda i: self.results_stack.setCurrentIndex(i))
        btn_row.addWidget(self.btn_tab_ok)
        btn_row.addWidget(self.btn_tab_err)
        right_lay.addLayout(btn_row)

        results_card = QFrame()
        results_card.setObjectName("card")
        card_lay = QVBoxLayout(results_card)
        card_lay.setContentsMargins(8, 8, 8, 8)

        self.results_stack = QStackedWidget()
        ok_page = QWidget()
        ok_lay = QVBoxLayout(ok_page)
        ok_lay.setContentsMargins(0, 0, 0, 0)
        self.scroll_ok, self.list_ok = self._make_scroll_list()
        ok_lay.addWidget(self.scroll_ok)
        err_page = QWidget()
        err_lay = QVBoxLayout(err_page)
        err_lay.setContentsMargins(0, 0, 0, 0)
        self.scroll_err, self.list_err = self._make_scroll_list()
        err_lay.addWidget(self.scroll_err)
        self.results_stack.addWidget(ok_page)
        self.results_stack.addWidget(err_page)
        card_lay.addWidget(self.results_stack, 1)
        right_lay.addWidget(results_card, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setHandleWidth(16)
        splitter.setChildrenCollapsible(False)
        lay.addWidget(splitter)
        return page

    # -- Import page (inside the Search tab) -- #

    def _build_import_page(self) -> QWidget:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        back_row = QHBoxLayout()
        self.btn_import_back = QPushButton(self.tr("back"))
        self.btn_import_back.setObjectName("danger")
        self.btn_import_back.clicked.connect(
            lambda: self.search_stack.setCurrentIndex(0))
        back_row.addWidget(self.btn_import_back)
        back_row.addStretch(1)
        lay.addLayout(back_row)

        header = QVBoxLayout()
        header.setSpacing(6)
        header.setContentsMargins(0, 6, 0, 0)
        self.lbl_import_title = QLabel(self.tr("import_title"))
        self.lbl_import_title.setFont(_qfont(FONTS["head"]))
        self.lbl_import_title.setAlignment(Qt.AlignCenter)
        header.addWidget(self.lbl_import_title)
        self.lbl_import_info = QLabel(self.tr("import_info"))
        self.lbl_import_info.setObjectName("muted")
        self.lbl_import_info.setFont(QFont(UI_FONT, 12))
        self.lbl_import_info.setAlignment(Qt.AlignCenter)
        self.lbl_import_info.setWordWrap(True)
        header.addWidget(self.lbl_import_info)
        lay.addLayout(header)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_select_dir = QPushButton(self.tr("select_mods_folder"))
        self.btn_select_dir.setObjectName("primary")
        self.btn_select_dir.setMinimumSize(220, 40)
        self.btn_select_dir.clicked.connect(self.start_import_scan)
        row.addWidget(self.btn_select_dir)
        row.addStretch(1)
        lay.addLayout(row)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(14, 12, 14, 14)
        log_lay.setSpacing(8)
        self.lbl_log_title = QLabel(self.tr("log"))
        self.lbl_log_title.setObjectName("muted")
        self.lbl_log_title.setFont(_qfont(FONTS["section"]))
        log_lay.addWidget(self.lbl_log_title)
        self.import_log = QPlainTextEdit()
        self.import_log.setReadOnly(True)
        self.import_log.setFont(_mono_font(10))
        log_lay.addWidget(self.import_log, 1)
        lay.addWidget(log_card, 1)
        return root

    # -- Transfer tab -- #

    def _build_transfer_tab(self) -> QWidget:
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 8, 8, 8)
        self.stages = QStackedWidget()
        self.stages.addWidget(self._build_stage_setup())
        self.stages.addWidget(self._build_stage_result())
        lay.addWidget(self.stages, 1)

        try:
            backups = self.backup_manager.list_backups()
            self._last_backup_dir = backups[0] if backups else None
        except Exception as e:
            logger.error("Failed to list backups: %s", e)
            self._last_backup_dir = None
        self._set_backup_button_state()
        return root

    def _build_stage_setup(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        header = QHBoxLayout()
        self.lbl_transfer_header = QLabel(self.tr("transfer_header"))
        self.lbl_transfer_header.setFont(_qfont(FONTS["head"]))
        header.addWidget(self.lbl_transfer_header)
        header.addStretch(1)
        self.lbl_step1 = QLabel(self.tr("step1"))
        self.lbl_step1.setObjectName("muted")
        header.addWidget(self.lbl_step1)
        lay.addLayout(header)

        path_row = QHBoxLayout()
        self.lbl_catalog_path = QLabel(self.tr(
            "catalog",
            path=str(self.profiles_path) if self.profiles_path else self.tr("catalog_undefined"),
        ))
        self.lbl_catalog_path.setObjectName("muted")
        path_row.addWidget(self.lbl_catalog_path, 1)
        self.btn_select_profiles_dir = QPushButton(self.tr("select_folder"))
        self.btn_select_profiles_dir.setObjectName("ghost")
        self.btn_select_profiles_dir.clicked.connect(self.select_profiles_dir)
        path_row.addWidget(self.btn_select_profiles_dir)
        lay.addLayout(path_row)

        prof_card = QFrame()
        prof_card.setObjectName("card")
        prof_lay = QVBoxLayout(prof_card)
        prof_lay.setContentsMargins(14, 10, 14, 10)
        prof_lay.setSpacing(6)
        head = QHBoxLayout()
        self.lbl_from = QLabel(self.tr("from_src"))
        self.lbl_from.setFont(_qfont(FONTS["section"]))
        head.addWidget(self.lbl_from, 1)
        self.lbl_to = QLabel(self.tr("to_dst"))
        self.lbl_to.setFont(_qfont(FONTS["section"]))
        self.lbl_to.setAlignment(Qt.AlignRight)
        head.addWidget(self.lbl_to, 1)
        prof_lay.addLayout(head)

        combo_row = QHBoxLayout()
        self.src_combo = QComboBox()
        self.src_combo.setMinimumHeight(32)
        self.src_combo.currentIndexChanged.connect(self.on_src_profile_changed)
        combo_row.addWidget(self.src_combo, 1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setIcon(QIcon(refresh_pixmap()))
        self.btn_refresh.setIconSize(QSize(18, 18))
        self.btn_refresh.setToolTip(self.tr("refresh_tip"))
        self.btn_refresh.setFixedSize(40, 32)
        self.btn_refresh.clicked.connect(lambda: self.refresh_profiles())
        combo_row.addWidget(self.btn_refresh)
        self.dst_combo = QComboBox()
        self.dst_combo.setMinimumHeight(32)
        combo_row.addWidget(self.dst_combo, 1)
        prof_lay.addLayout(combo_row)
        lay.addWidget(prof_card)

        self.transfer_frame = QFrame()
        self.transfer_frame.setObjectName("card")
        tf_lay = QVBoxLayout(self.transfer_frame)
        tf_lay.setContentsMargins(14, 10, 14, 12)
        tf_lay.setSpacing(6)
        self.transfer_title = QLabel(self.tr("what_to_transfer"))
        self.transfer_title.setFont(_qfont(FONTS["head"]))
        tf_lay.addWidget(self.transfer_title)
        self.checks_scroll, self.checks_list = self._make_scroll_list()
        self.checks_scroll.setMinimumHeight(120)
        tf_lay.addWidget(self.checks_scroll, 1)
        lay.addWidget(self.transfer_frame, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.btn_next = QPushButton(self.tr("next"))
        self.btn_next.setObjectName("primary")
        self.btn_next.setMinimumSize(180, 40)
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self._go_to_stage_result)
        nav.addWidget(self.btn_next)
        lay.addLayout(nav)
        return page

    def _build_stage_result(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.btn_back = QPushButton(self.tr("back"))
        self.btn_back.setObjectName("danger")
        self.btn_back.clicked.connect(self._go_to_stage_setup)
        top.addWidget(self.btn_back)
        self.lbl_stage_result_title = QLabel("")
        self.lbl_stage_result_title.setObjectName("muted")
        top.addWidget(self.lbl_stage_result_title, 1)
        self.lbl_step2 = QLabel(self.tr("step2"))
        self.lbl_step2.setObjectName("muted")
        top.addWidget(self.lbl_step2)
        lay.addLayout(top)

        actions = QHBoxLayout()
        self.btn_rollback = QPushButton(self.tr("rollback"))
        self.btn_rollback.setObjectName("danger")
        self.btn_rollback.setMinimumSize(260, 40)
        self.btn_rollback.setEnabled(False)
        self.btn_rollback.clicked.connect(self.rollback_last_transfer)
        actions.addWidget(self.btn_rollback)
        self.btn_cancel_transfer = QPushButton(self.tr("cancel"))
        self.btn_cancel_transfer.setObjectName("danger")
        self.btn_cancel_transfer.setVisible(False)
        self.btn_cancel_transfer.clicked.connect(self._on_cancel_clicked)
        actions.addWidget(self.btn_cancel_transfer)
        actions.addStretch(1)
        lay.addLayout(actions)

        self.lbl_analysis_result = QLabel(self.tr("analysis_result"))
        self.lbl_analysis_result.setObjectName("muted")
        self.lbl_analysis_result.setFont(_qfont(FONTS["section"]))
        lay.addWidget(self.lbl_analysis_result)

        self.analysis_tabs = QTabWidget()
        ok_page = QWidget()
        ok_lay = QVBoxLayout(ok_page)
        self.analysis_scroll_ok, self.analysis_list_ok = self._make_scroll_list()
        ok_lay.addWidget(self.analysis_scroll_ok)
        err_page = QWidget()
        err_lay = QVBoxLayout(err_page)
        self.analysis_scroll_err, self.analysis_list_err = self._make_scroll_list()
        err_lay.addWidget(self.analysis_scroll_err)
        self.analysis_tabs.addTab(ok_page, self.tr("tab_available"))
        self.analysis_tabs.addTab(err_page, self.tr("tab_not_found"))
        lay.addWidget(self.analysis_tabs, 1)
        return page

    # -- settings -- #

    def load_settings(self):
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding='utf-8'))
                ver = data.get('version') or self._default_mc_version()
                self.cmb_version.blockSignals(True)
                self.cmb_version.setCurrentText(ver)
                self.cmb_version.blockSignals(False)
                loader = data.get('loader', 'fabric')
                idx = self.cmb_loader.findText(loader)
                if idx >= 0:
                    self.cmb_loader.blockSignals(True)
                    self.cmb_loader.setCurrentIndex(idx)
                    self.cmb_loader.blockSignals(False)
                self.txt_mods.blockSignals(True)
                self.txt_mods.setPlainText(data.get('mods', ''))
                self.txt_mods.blockSignals(False)
                lang = str(data.get('lang', self.lang)).lower()
                if lang in SUPPORTED_LANGUAGES and lang != self.lang:
                    self.lang = lang
                    self.api.set_lang(lang)
                    self.apply_language()
            except Exception as e:
                logger.error("Failed to load settings: %s", e)

    def delayed_save(self):
        self._save_timer.stop()
        self._save_timer.start(1000)

    def save_settings(self):
        data = {
            'version': self.cmb_version.currentText(),
            'loader': self.cmb_loader.currentText(),
            'mods': self.txt_mods.toPlainText(),
            'lang': self.lang,
        }
        try:
            self.config_file.write_text(
                json.dumps(data, indent=4, ensure_ascii=False), encoding='utf-8')
            self.lbl_save_notify.setText(self.tr("synced"))
            QTimer.singleShot(2000, lambda: self.lbl_save_notify.setText(""))
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    # -- Minecraft versions -- #

    def _default_mc_version(self) -> str:
        return "1.21.1"

    def _start_mc_versions_load(self):
        def worker():
            try:
                versions = fetch_minecraft_release_versions_ordered()
            except Exception as e:
                logger.error("Failed to load MC versions: %s", e)
                self._lists.versions_failed.emit(str(e))
                return
            self._mc_release_versions_cache = frozenset(versions)
            self._lists.versions_loaded.emit(versions)
        threading.Thread(target=worker, daemon=True).start()

    def _on_mc_versions_loaded(self, versions: list):
        self._mc_version_values = versions
        current = self.cmb_version.currentText().strip()
        if not current or current == _t("loading", "ru") or current == _t("loading", "en"):
            current = self._default_mc_version()
        self.cmb_version.blockSignals(True)
        self.cmb_version.clear()
        self.cmb_version.addItems(versions)
        self.cmb_version.setCurrentText(current if current else self._default_mc_version())
        self.cmb_version.blockSignals(False)
        self._mc_versions_loaded = True

    def _on_mc_versions_failed(self, error: str):
        self.cmb_version.blockSignals(True)
        self.cmb_version.clear()
        self.cmb_version.addItems(["1.21.4", "1.21.1", "1.20.1"])
        self.cmb_version.setCurrentText("1.21.4")
        self.cmb_version.blockSignals(False)
        self.set_status(self.tr("mc_versions_failed", error=error), "error")
        QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle"), "muted"))

    def ensure_valid_mc_version(self) -> bool:
        version = self.cmb_version.currentText().strip()
        if not version:
            self._tell(QMessageBox.Warning, self.tr("dlg_mc_title"), self.tr("dlg_mc_empty"))
            return False
        if not self._mc_versions_loaded:
            return True
        releases = self._mc_release_versions_cache or frozenset()
        if releases and version not in releases:
            ret = self._ask(
                QMessageBox.Question, self.tr("dlg_mc_title"),
                self.tr("dlg_mc_unknown", version=version),
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            return ret == QMessageBox.Ok
        return True

    # -- status / progress -- #

    def set_status(self, text: str, kind: str = "muted"):
        self.lbl_status.setText(text)
        self.lbl_status.setObjectName("accent" if kind == "ok" else "error" if kind == "error" else "muted")
        # Re-applying objectName needs an explicit style repolish.
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def update_ui_progress(self, text: str, prog: float):
        self.set_status(text)
        pct = int(max(0.0, min(1.0, prog)) * 100)
        self.progress.setValue(pct)
        self.lbl_progress_percent.setText(f"{pct}%")

    # -- folders / profiles -- #

    def open_app_folder(self):
        ok, err = open_folder(self.app_path)
        if not ok:
            self.set_status(self.tr("folder_open_failed", error=err or self.tr("unknown")), "error")
            QTimer.singleShot(4000, lambda: self.set_status(self.tr("idle")))

    def select_profiles_dir(self):
        initial = str(self.profiles_path) if (self.profiles_path and self.profiles_path.exists()) else str(self.app_path)
        directory = QFileDialog.getExistingDirectory(self, self.tr("select_folder"), initial)
        if not directory:
            return
        self.profiles_path = Path(directory)
        self.lbl_catalog_path.setText(self.tr("catalog", path=str(self.profiles_path)))
        self.refresh_profiles()

    def _set_profiles(self, combo: QComboBox, profiles: List[str], keep: str):
        combo.blockSignals(True)
        combo.clear()
        if not profiles:
            combo.addItem(self.no_profiles_text(), None)
        else:
            combo.addItem(self.profile_placeholder(), None)
            for p in profiles:
                combo.addItem(p, p)
            if keep and keep in profiles:
                combo.setCurrentIndex(combo.findData(keep))
        # The placeholder shows in the field but is hidden from the
        # open list (no need to select it back). The lone "(no profiles)"
        # entry stays visible, or the list would open empty.
        try:
            combo.view().setRowHidden(0, len(profiles) > 0)
        except Exception as e:
            logger.debug("Failed to hide placeholder: %s", e)
        combo.blockSignals(False)

    def _current_profile(self, combo: QComboBox) -> str:
        data = combo.currentData()
        return data if isinstance(data, str) else ""

    def _scan_profiles(self) -> List[str]:
        if self.profiles_path and self.profiles_path.exists():
            return sorted(d.name for d in self.profiles_path.iterdir() if d.is_dir())
        return []

    def refresh_profiles(self, silent: bool = False):
        keep_src = self._current_profile(self.src_combo) if hasattr(self, "src_combo") else ""
        keep_dst = self._current_profile(self.dst_combo) if hasattr(self, "dst_combo") else ""
        if not silent:
            self.btn_refresh.setEnabled(False)
            self.set_status(self.tr("profiles_updating"))
        else:
            # Placeholder until the first load finishes.
            if self.src_combo.count() == 0:
                self._set_profiles(self.src_combo, [], "")
                self._set_profiles(self.dst_combo, [], "")

        def worker():
            profiles = self._scan_profiles()
            self._lists.profiles_loaded.emit((profiles, keep_src, keep_dst, silent))
        threading.Thread(target=worker, daemon=True).start()

    def load_profiles_list(self):
        self.refresh_profiles(silent=True)

    def _on_profiles_loaded(self, payload):
        profiles, keep_src, keep_dst, silent = payload
        self._set_profiles(self.src_combo, profiles, keep_src)
        self._set_profiles(self.dst_combo, profiles, keep_dst)
        src = self._current_profile(self.src_combo)
        # Never hide the card: a hidden stretch=1 widget makes the layout
        # smear spare space between the remaining rows. The empty state
        # shows a placeholder instead (see on_src_profile_changed).
        self.on_src_profile_changed()
        self.btn_refresh.setEnabled(True)
        if not silent:
            self.set_status(self.tr("profiles_updated"), "ok")
            QTimer.singleShot(2000, lambda: self.set_status(self.tr("idle")))

    def _show_checks_placeholder(self, text: str):
        """Empty state of the transfer list (the card is never hidden)."""
        _clear_layout(self.checks_list)
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lbl.setAlignment(Qt.AlignCenter)
        self.checks_list.insertWidget(self.checks_list.count() - 1, lbl)

    def on_src_profile_changed(self, *_args):
        name = self._current_profile(self.src_combo)
        _clear_layout(self.checks_list)
        self.available_items = {}
        self.transfer_frame.setVisible(True)
        if not name or not self.profiles_path:
            self._show_checks_placeholder(self.profile_placeholder())
            self.btn_next.setEnabled(False)
            return
        src_path = self.profiles_path / name
        if not src_path.exists():
            self._show_checks_placeholder(self.tr("no_items"))
            self.btn_next.setEnabled(False)
            return
        items = []
        for item in src_path.iterdir():
            if item.name in PROFILE_TRANSFER_HIDE_NAMES:
                continue
            if any(item.name.startswith(p) for p in PROFILE_TRANSFER_HIDE_PREFIXES):
                continue
            if item.is_dir():
                items.append(('dir', item.name))
            elif item.is_file() and item.name == 'options.txt':
                items.append(('file', item.name))
        items.sort(key=lambda x: x[1])
        descriptions = self._transfer_descriptions()
        for item_type, item_name in items:
            desc = descriptions.get(item_name, "")
            prefix = "📂 " if item_type == "dir" else "📄 "
            text = f"{prefix}{item_name} → {desc}" if desc else f"{prefix}{item_name}"
            cb = QCheckBox(text)
            cb.setFont(QFont(UI_FONT, 13))
            cb.setChecked(item_name in PROFILE_TRANSFER_DEFAULT_CHECKED)
            self.checks_list.insertWidget(self.checks_list.count() - 1, cb)
            self.available_items[item_name] = {
                "type": item_type, "path": item_name, "desc": desc,
                "checkbox": cb,
            }
        if not items:
            lbl = QLabel(self.tr("no_items"))
            lbl.setObjectName("error")
            self.checks_list.insertWidget(self.checks_list.count() - 1, lbl)
        _clear_layout(self.analysis_list_ok)
        _clear_layout(self.analysis_list_err)
        self.btn_next.setEnabled(bool(self.available_items))

    # -- transfer wizard -- #

    def _show_stage(self, name: str):
        if name == "setup":
            self.stages.setCurrentIndex(0)
            self._current_stage = "setup"
        elif name == "result":
            self.stages.setCurrentIndex(1)
            self._current_stage = "result"
        else:
            raise ValueError(f"Unknown stage: {name}")

    def _go_to_stage_result(self):
        if not self.btn_next.isEnabled():
            return
        if self._transfer_busy:
            self.set_status(self.tr("transferring"), "error")
            QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))
            return
        # Confirmations and backup first; stage 2 only on approval.
        # Next then starts the transfer immediately (no separate button).
        plan = self._prepare_transfer()
        if plan is None:
            return
        self.lbl_stage_result_title.setText(f"{plan['src_name']}  →  {plan['dst_name']}")
        self._set_backup_button_state()
        self._show_stage("result")
        self._execute_transfer(plan)

    def _go_to_stage_setup(self):
        if self._transfer_busy:
            ret = self._ask(
                QMessageBox.Question,
                self.tr("dlg_transfer_busy_title"), self.tr("dlg_transfer_busy"),
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if ret != QMessageBox.Ok:
                return
        self._show_stage("setup")

    def _set_backup_button_state(self):
        ok = self._last_backup_dir is not None and self._last_backup_dir.exists()
        self.btn_rollback.setEnabled(bool(ok) and not self._transfer_busy)

    def _set_transfer_busy(self, busy: bool):
        self._transfer_busy = busy
        if busy:
            self.btn_rollback.setEnabled(False)
        else:
            self._set_backup_button_state()

    def rollback_last_transfer(self):
        if self._last_backup_dir is None or not self._last_backup_dir.exists():
            self._tell(QMessageBox.Warning, self.tr("dlg_rollback_title"),
                       self.tr("dlg_rollback_no_backup"))
            return
        ret = self._ask(
            QMessageBox.Question, self.tr("dlg_rollback_confirm_title"),
            self.tr("dlg_rollback_confirm", backup=self._last_backup_dir.name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        backup = self._last_backup_dir
        self.btn_rollback.setEnabled(False)
        self.btn_rollback.setText(self.tr("rollback_short"))

        def worker():
            ok = self.backup_manager.restore(backup)
            self._lists.rollback_done.emit(bool(ok))
        threading.Thread(target=worker, daemon=True).start()

    def _on_rollback_done(self, ok: bool):
        self.btn_rollback.setText(self.tr("rollback"))
        if ok:
            self._tell(QMessageBox.Information, self.tr("dlg_rollback_title"), self.tr("dlg_rollback_ok"))
            self.set_status(self.tr("rollback_done"), "ok")
            self._last_backup_dir = None
        else:
            self._tell(QMessageBox.Critical, self.tr("dlg_rollback_title"), self.tr("dlg_rollback_fail"))
        self._set_backup_button_state()

    # -- cards -- #

    def _clear_results(self):
        _clear_layout(self.list_ok)
        _clear_layout(self.list_err)

    def _clear_analysis(self):
        _clear_layout(self.analysis_list_ok)
        _clear_layout(self.analysis_list_err)

    def _card(self, kind: str) -> tuple[QFrame, QBoxLayout]:
        frame = QFrame()
        frame.setObjectName({
            "ok": "card-ok", "err": "card-err",
            "warn": "card-warn", "info": "card-info",
        }.get(kind, "card-ok"))
        # Content-sized cards only: without Maximum the layout sometimes
        # stretches them across the whole scroll height (stale heightForWidth
        # of wordWrap labels inside QScrollArea).
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        return frame, lay

    def _icon_label(self) -> QLabel:
        lbl = QLabel("⌛")
        lbl.setFixedSize(42, 42)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"background: {COLORS['input']}; border-radius: 6px; color: {COLORS['muted']};")
        return lbl

    def load_icon(self, url: str, label: QLabel):
        if not url:
            return
        with self._image_lock:
            cached = self.image_cache.get(url)
            if cached is not None and not cached.isNull():
                pix = cached
            else:
                pix = None
                if url in self._icon_inflight:
                    return
                self._icon_inflight.add(url)
        if pix is not None:
            try:
                label.setPixmap(pix)
                label.setText("")
            except RuntimeError:
                pass
            return

        def worker():
            try:
                # QImage only here; QPixmap is created in the GUI thread.
                resp = self.api.session.get(url, timeout=10)
                resp.raise_for_status()
                img = QImage.fromData(resp.content)
                if img.isNull():
                    raise ValueError("bad image")
                scaled = img.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._icons.loaded.emit(label, {"url": url, "img": scaled})
            except Exception:
                with self._image_lock:
                    self._icon_inflight.discard(url)
                self._icons.failed.emit(label)
        threading.Thread(target=worker, daemon=True).start()

    def _on_icon_loaded(self, label, payload):
        try:
            if isinstance(payload, dict):
                url = payload.get("url")
                img = payload.get("img")
            else:  # backward compat: raw QImage/QPixmap
                url, img = None, payload
            pix = QPixmap.fromImage(img) if isinstance(img, QImage) else img
            if url:
                with self._image_lock:
                    self.image_cache[url] = pix
                    while len(self.image_cache) > self.IMAGE_CACHE_LIMIT:
                        self.image_cache.popitem(last=False)
                    self._icon_inflight.discard(url)
            label.setPixmap(pix)
            label.setText("")
        except RuntimeError:
            pass  # widget already destroyed
        except Exception:
            try:
                self._on_icon_failed(label)
            except Exception:
                pass

    def _on_icon_failed(self, label):
        try:
            label.setText("📦")
        except RuntimeError:
            pass

    def add_mod_card(self, info: dict):
        frame, lay = self._card("ok")
        icon = self._icon_label()
        lay.addWidget(icon)
        if info.get('icon_url'):
            self.load_icon(info['icon_url'], icon)
        text_box = QVBoxLayout()
        name = QLabel(info.get('name', '?'))
        name.setFont(_qfont(FONTS["section"]))
        text_box.addWidget(name)
        ver = QLabel(f"v{info.get('version_number', '?')}")
        ver.setObjectName("muted")
        text_box.addWidget(ver)
        lay.addLayout(text_box, 1)
        btn = QPushButton()
        btn.setObjectName("delbtn")
        btn.setIcon(QIcon(cross_pixmap()))
        btn.setIconSize(QSize(16, 16))
        btn.setFixedSize(30, 30)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(self.tr("remove_tip"))
        btn.clicked.connect(lambda: self.remove_found(frame, info))
        lay.addWidget(btn)
        self.list_ok.insertWidget(self.list_ok.count() - 1, frame)
        self._scroll_to_bottom(self.scroll_ok)

    def add_error_card(self, name: str):
        frame, lay = self._card("err")
        lbl = QLabel(self.tr("card_not_found", name=name))
        lbl.setObjectName("error")
        lbl.setWordWrap(True)
        lay.addWidget(lbl, 1)
        self.list_err.insertWidget(self.list_err.count() - 1, frame)
        self._scroll_to_bottom(self.scroll_err)

    def add_rate_limited_card(self, name: str):
        frame, lay = self._card("warn")
        lbl = QLabel(self.tr("card_rate_limited", name=name))
        lbl.setWordWrap(True)
        lay.addWidget(lbl, 1)
        self.list_err.insertWidget(self.list_err.count() - 1, frame)
        self._scroll_to_bottom(self.scroll_err)

    def add_warning_card(self, name: str, reason: str, icon_url=None):
        frame, lay = self._card("warn")
        icon = self._icon_label()
        icon.setText("⚠")
        lay.addWidget(icon)
        if icon_url:
            self.load_icon(icon_url, icon)
        box = QVBoxLayout()
        n = QLabel(name)
        n.setFont(_qfont(FONTS["section"]))
        box.addWidget(n)
        r = QLabel(reason)
        r.setWordWrap(True)
        box.addWidget(r)
        lay.addLayout(box, 1)
        self.list_err.insertWidget(self.list_err.count() - 1, frame)
        self._scroll_to_bottom(self.scroll_err)

    def add_ambiguous_card(self, query: str, candidates: list):
        frame = QFrame()
        frame.setObjectName("card-info")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(frame)
        title = QLabel(self.tr("card_ambiguous", query=query))
        title.setWordWrap(True)
        lay.addWidget(title)
        for c in candidates[:5]:
            row = QHBoxLayout()
            authors = ", ".join(c.get('authors') or []) or "—"
            dl = f"{c.get('downloads', 0):,}".replace(",", " ")
            lbl = QLabel(f"{c.get('name')}  ·  {authors}  ·  {self.tr('downloads', n=dl)}")
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            btn = QPushButton(self.tr("select"))
            btn.setObjectName("primary")
            btn.clicked.connect(
                lambda _=False, cid=c['project_id'], q=query, card=frame:
                    self._pick_candidate(cid, q, card))
            row.addWidget(btn)
            lay.addLayout(row)
        self.list_err.insertWidget(self.list_err.count() - 1, frame)
        self._scroll_to_bottom(self.scroll_err)

    def _pick_candidate(self, project_id: str, query: str, card=None):
        if card is not None:
            card.deleteLater()
        version = self.cmb_version.currentText()
        loader = self.cmb_loader.currentText()
        bus = BusSignals()
        bus.done.connect(lambda res: self._on_candidate_resolved(res, query))

        def worker():
            result = self.api.resolve_by_project_id(project_id, version, loader)
            bus.done.emit(result)
        threading.Thread(target=worker, daemon=True).start()

    def _on_candidate_resolved(self, result: dict, query: str):
        status = result.get('status')
        if status == STATUS_FOUND:
            self.found_mods.append(result)
            self.add_mod_card(result)
            self._show_download_button()
        elif status == STATUS_NO_VERSION:
            self.add_warning_card(
                result.get('name') or query,
                result.get('reason') or self.tr('no_version_default'),
                result.get('icon_url'))
        else:
            self.add_error_card(result.get('name') or query)

    def remove_found(self, card, info):
        card.deleteLater()
        if info in self.found_mods:
            self.found_mods.remove(info)
        if not self.found_mods:
            self.btn_download.setVisible(False)
            self.btn_download.setEnabled(False)

    # -- search: check / download -- #

    def _show_download_button(self):
        self.btn_download.setVisible(True)
        self.btn_download.setEnabled(True)

    def _begin_cancel(self, button: QPushButton, key: str = "default") -> threading.Event:
        ev = threading.Event()
        if not hasattr(self, "_cancel_events") or not isinstance(self._cancel_events, dict):
            self._cancel_events = {}
        self._cancel_events[key] = ev
        # compat: keep single ref for legacy callers
        self._cancel_event = ev
        button.setVisible(True)
        button.setEnabled(True)
        button.setText(self.tr("cancel"))
        return ev

    def _end_cancel(self, button: QPushButton, key: str = "default"):
        button.setVisible(False)
        try:
            events = getattr(self, "_cancel_events", {})
            events.pop(key, None)
        except Exception:
            pass
        if key == "default" or getattr(self, "_cancel_event", None) is not None:
            # point legacy ref to any remaining event, else None
            try:
                remaining = list(getattr(self, "_cancel_events", {}).values())
                self._cancel_event = remaining[-1] if remaining else None
            except Exception:
                self._cancel_event = None

    def _on_cancel_clicked(self):
        for ev in list(getattr(self, "_cancel_events", {}).values()):
            try:
                ev.set()
            except Exception:
                pass
        if getattr(self, "_cancel_event", None) is not None:
            try:
                self._cancel_event.set()
            except Exception:
                pass
        for btn in (getattr(self, "btn_cancel_search", None),
                    getattr(self, "btn_cancel_transfer", None)):
            try:
                if btn is not None:
                    btn.setEnabled(False)
                    btn.setText(self.tr("canceling"))
            except Exception:
                pass

    def start_check(self):
        self.save_settings()
        mods = [m.strip() for m in self.txt_mods.toPlainText().split('\n') if m.strip()]
        if not mods:
            self.set_status(self.tr("empty_list"), "error")
            QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))
            return
        if not self.ensure_valid_mc_version():
            return
        cancel_event = self._begin_cancel(self.btn_cancel_search, key="search")
        self.btn_check.setEnabled(False)
        self.btn_download.setVisible(False)
        self.btn_download.setEnabled(False)
        self._clear_results()
        self.found_mods = []
        self.btn_tab_ok.setChecked(True)
        self.results_stack.setCurrentIndex(0)

        bus = BusSignals()
        bus.progress.connect(self._on_check_progress)
        bus.done.connect(self._render_search_summary)
        version = self.cmb_version.currentText()
        loader = self.cmb_loader.currentText()

        def on_progress(p: TransferProgress):
            bus.progress.emit(p, p.percent)

        def on_done(summary: TransferSummary):
            bus.done.emit(summary)

        def worker():
            try:
                self.search_check_service.execute(
                    mod_names=mods, mc_version=version, loader=loader,
                    callbacks=TransferCallbacks(on_progress=on_progress, on_done=on_done),
                    cancel_event=cancel_event)
            finally:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _on_check_progress(self, payload, _percent):
        p = payload
        if isinstance(p, TransferProgress):
            self.update_ui_progress(
                self.tr("analysis_progress", name=p.current_name, done=p.done, total=p.total),
                p.percent)
        else:
            self.update_ui_progress(str(p), float(_percent or 0.0))

    def _render_search_summary(self, summary: TransferSummary):
        self._end_cancel(self.btn_cancel_search, key="search")
        self.found_mods = []
        for r in summary.results:
            if r.status == SingleResultStatus.OK and r.mod_info:
                self.found_mods.append(r.mod_info)
                self.add_mod_card(r.mod_info)
            elif r.status == SingleResultStatus.NO_VERSION:
                name = (r.mod_info or {}).get('name') or r.jar_name
                self.add_warning_card(name, r.error or self.tr('no_version_default'),
                                      (r.mod_info or {}).get('icon_url'))
            elif r.status == SingleResultStatus.AUTHOR_MISMATCH:
                name = (r.mod_info or {}).get('name') or r.jar_name
                self.add_warning_card(name, r.error or self.tr('author_mismatch_default'),
                                      (r.mod_info or {}).get('icon_url'))
            elif r.status == SingleResultStatus.AMBIGUOUS:
                self.add_ambiguous_card(r.jar_name, r.candidates or [])
            elif r.status == SingleResultStatus.RATE_LIMITED:
                self.add_rate_limited_card(r.jar_name)
            elif r.status == SingleResultStatus.READ_ERROR:
                self.add_error_card(self.tr(
                    "card_read_error", name=r.jar_name,
                    error=r.error or self.tr("unknown")))
            else:
                self.add_error_card(r.jar_name)
        found, total = summary.ok, summary.total
        final = (self.tr("check_cancelled", found=found, total=total)
                 if summary.cancelled else self.tr("check_done", found=found, total=total))
        self.update_ui_progress(final, 1.0)
        self.set_status(final, "ok" if found else "error")
        self.btn_check.setEnabled(True)
        if self.found_mods:
            self._show_download_button()

    def start_download(self):
        if not self.found_mods:
            self.set_status(self.tr("no_mods_to_download"), "error")
            QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))
            return
        if not self.ensure_valid_mc_version():
            return
        safe_ver = sanitize_version_text(self.cmb_version.currentText().strip())
        folder = self.downloads_base / f"mods_{datetime.now().strftime('%H%M%S')}-{safe_ver}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Cannot create folder %s: %s", folder, e)
            self.set_status(str(e), "error")
            return
        self.btn_download.setEnabled(False)
        self.btn_check.setEnabled(False)
        cancel_event = self._begin_cancel(self.btn_cancel_search, key="search")
        bus = BusSignals()
        bus.progress.connect(self.update_ui_progress)
        bus.done.connect(lambda _=None: self._on_download_finished(folder))
        items = list(self.found_mods)

        def worker():
            total = len(items)
            for i, mod in enumerate(items):
                if cancel_event.is_set():
                    break
                bus.progress.emit(self.tr("download_file", name=mod['name']), (i + 1) / total)
                try:
                    filename = sanitize_filename(mod.get('filename') or f"{mod.get('name', 'mod')}.jar")
                    ok, err = download_url_to_file(
                        mod.get('download_url', ''), folder / filename,
                        session=getattr(self.api, 'session', None),
                        timeout=30,
                        expected_sha1=mod.get('file_sha1'),
                        expected_size=mod.get('file_size'),
                    )
                    if not ok:
                        logger.error("Failed to download %s: %s", mod.get('name'), err)
                except Exception as e:
                    logger.error("Failed to download %s: %s", mod.get('name'), e)
            bus.progress.emit(self.tr("download_finished_folder", folder=folder.name), 1.0)
            bus.done.emit(None)
        threading.Thread(target=worker, daemon=True).start()

    def _on_download_finished(self, folder: Path):
        self.btn_check.setEnabled(True)
        self.btn_download.setEnabled(True)
        self._end_cancel(self.btn_cancel_search, key="search")
        self.set_status(self.tr("download_finished"), "ok")
        QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))

    # -- import -- #

    def _log_insert(self, text: str, color: Optional[str] = None):
        cursor = self.import_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        if color == "success":
            fmt.setForeground(QColor(COLORS["accent"]))
        elif color == "fail":
            fmt.setForeground(QColor(COLORS["error_fg"]))
        cursor.insertText(text, fmt)
        self.import_log.setTextCursor(cursor)
        self.import_log.ensureCursorVisible()

    def start_import_scan(self):
        directory = QFileDialog.getExistingDirectory(self, self.tr("select_mods_folder"))
        if not directory:
            return
        self.btn_select_dir.setEnabled(False)
        self.import_log.clear()
        self._log_insert(self.tr("import_scanning", dir=directory))
        folder = Path(directory)
        bus = BusSignals()
        bus.progress.connect(self._on_import_progress)
        bus.done.connect(self._render_import_summary)

        def on_progress(p: ImportProgress):
            bus.progress.emit(p, p.percent)

        def on_done(summary: ImportSummary):
            bus.done.emit(summary)

        def worker():
            self.import_scan_service.execute(
                folder, callbacks=ImportCallbacks(on_progress=on_progress, on_done=on_done))
        threading.Thread(target=worker, daemon=True).start()

    def _on_import_progress(self, payload, _percent):
        p = payload
        if isinstance(p, ImportProgress):
            self.update_ui_progress(
                self.tr("import_scan", name=p.current_name, done=p.done, total=p.total),
                p.percent)
        else:
            self.update_ui_progress(str(p), float(_percent or 0.0))

    def append_to_main_list(self, names: list):
        current = self.txt_mods.toPlainText().strip()
        existing = {l.strip().lower() for l in current.split('\n') if l.strip()}
        new_entries = [n for n in names if n.lower() not in existing]
        if new_entries:
            sep = "\n" if current else ""
            self.txt_mods.setPlainText(current + sep + "\n".join(new_entries) if current
                                       else "\n".join(new_entries))
            self.save_settings()
            bar = self.txt_mods.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _render_import_summary(self, summary: ImportSummary):
        ok_hash = sum(1 for r in summary.results if r.status == ImportItemStatus.OK_HASH)
        ok_meta = sum(1 for r in summary.results if r.status == ImportItemStatus.OK_META)
        unknown = sum(1 for r in summary.results if r.status == ImportItemStatus.UNKNOWN)
        errors = sum(1 for r in summary.results if r.status == ImportItemStatus.READ_ERROR)
        for r in summary.results:
            if r.status == ImportItemStatus.OK_HASH:
                self._log_insert(self.tr("import_found_hash", name=r.display_name), "success")
            elif r.status == ImportItemStatus.OK_META:
                self._log_insert(self.tr("import_found_meta", name=r.display_name), "success")
            elif r.status == ImportItemStatus.READ_ERROR:
                self._log_insert(self.tr("import_read_error", jar=r.jar_name, error=r.error))
            else:
                self._log_insert(self.tr("import_unknown", jar=r.jar_name), "fail")
        names = summary.recognized_names()
        if names:
            self.txt_mods.setPlainText("")
            self.append_to_main_list(names)
        total = summary.total
        self._log_insert(self.tr("import_summary", ok=summary.ok, total=total,
                                 h=ok_hash, m=ok_meta, u=unknown, e=errors))
        self.btn_select_dir.setEnabled(True)
        self.set_status(self.tr("import_done", ok=summary.ok, total=total),
                        "ok" if summary.ok else "error")
        QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))

    # -- transfer -- #

    def _transfer_descriptions(self) -> dict:
        return {
            "config": self.tr("desc_config"),
            "shaderpacks": self.tr("desc_shaderpacks"),
            "resourcepacks": self.tr("desc_resourcepacks"),
            "mods": self.tr("desc_mods"),
            "saves": self.tr("desc_saves"),
            "screenshots": self.tr("desc_screenshots"),
            "options.txt": self.tr("desc_options"),
            "schematics": self.tr("desc_schematics"),
            "xaero": self.tr("desc_xaero"),
        }

    def _prepare_transfer(self) -> Optional[dict]:
        """Validation + confirmations + backup BEFORE entering stage 2.

        Returns the run plan, or None if the user cancelled any dialog
        (we stay on stage 1).
        """
        src_name = self._current_profile(self.src_combo)
        dst_name = self._current_profile(self.dst_combo)
        if not src_name or not dst_name:
            self.set_status(self.tr("select_both_profiles"), "error")
            QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))
            return None
        src_path = self.profiles_path / src_name
        dst_path = self.profiles_path / dst_name
        if not src_path.exists():
            self.set_status(self.tr("src_not_found", name=src_name), "error")
            return None
        if not dst_path.exists():
            self.set_status(self.tr("dst_not_found", name=dst_name), "error")
            return None
        to_transfer = [n for n, i in self.available_items.items() if i["checkbox"].isChecked()]
        if not to_transfer:
            self.set_status(self.tr("nothing_selected"), "error")
            QTimer.singleShot(3000, lambda: self.set_status(self.tr("idle")))
            return None
        if "mods" in to_transfer and not self.ensure_valid_mc_version():
            return None
        if "mods" in to_transfer and self.available_items.get("mods", {}).get("type") == "dir":
            mods_src = src_path / "mods"
            if mods_src.is_dir():
                n_mods = len(list(mods_src.glob("*.jar")))
                if n_mods > 0:
                    ret = self._ask(
                        QMessageBox.Question, self.tr("dlg_mods_title"),
                        self.tr("dlg_mods_text", n=n_mods),
                        QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
                    if ret != QMessageBox.Ok:
                        return None
        try:
            backup_dir = self.backup_manager.prepare(
                src_profile_path=src_path, src_profile_name=src_name,
                target_profile_path=dst_path, target_profile_name=dst_name,
                items_to_transfer=to_transfer,
                mc_version=self.cmb_version.currentText().strip(),
                loader=self.cmb_loader.currentText().strip())
            self._last_backup_dir = backup_dir
            self._set_backup_button_state()
            self.set_status(self.tr("backup_created", name=backup_dir.name), "ok")
        except Exception as e:
            logger.exception("Failed to create backup: %s", e)
            ret = self._ask(
                QMessageBox.Question, self.tr("dlg_backup_fail_title"),
                self.tr("dlg_backup_fail", e=e),
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if ret != QMessageBox.Ok:
                return None
            self._last_backup_dir = None

        return {
            "src_name": src_name, "dst_name": dst_name,
            "src_path": src_path, "dst_path": dst_path,
            "to_transfer": to_transfer,
        }

    def _execute_transfer(self, plan: dict):
        """Run the transfer. Called on stage 2, no questions asked."""
        src_path = plan["src_path"]
        dst_path = plan["dst_path"]
        to_transfer = list(plan["to_transfer"])
        # Snapshot item types: GUI may rebuild available_items mid-transfer.
        items_snapshot = {
            n: {"type": self.available_items.get(n, {}).get("type", "dir")}
            for n in to_transfer
        }

        self._clear_analysis()
        self._set_transfer_busy(True)
        cancel_event = self._begin_cancel(self.btn_cancel_transfer, key="transfer")
        bus = BusSignals()
        bus.progress.connect(self._on_transfer_progress)
        bus.done.connect(lambda s: self._on_transfer_done(s, dst_path))

        mc_version = self.cmb_version.currentText().strip()
        loader = self.cmb_loader.currentText().strip()

        def worker():
            mods_summary: Optional[TransferSummary] = None
            # Extra files written by copy_folder / single-file copy,
            # merged into the backup manifest on done.
            extra_new: Dict[str, List[str]] = {}
            try:
                def on_progress(p: TransferProgress):
                    bus.progress.emit(p, 0.0)

                # TransferService also emits on_done; swallow it here and
                # emit a single final done after ALL items are copied.
                transfer_callbacks = TransferCallbacks(
                    on_progress=on_progress, on_done=None)
                for item_name in to_transfer:
                    if cancel_event.is_set():
                        break
                    info = items_snapshot.get(item_name, {"type": "dir"})
                    src_item = src_path / item_name
                    dst_item = dst_path / item_name
                    if item_name == "mods" and info["type"] == "dir":
                        mods_summary = self.transfer_service.execute(
                            src_folder=src_item, dst_folder=dst_item,
                            mc_version=mc_version, loader=loader,
                            callbacks=transfer_callbacks, cancel_event=cancel_event)
                    elif info["type"] == "dir":
                        copied = self.copy_folder(
                            src_item, dst_item, item_name, bus,
                            cancel_event=cancel_event)
                        if copied:
                            extra_new.setdefault(item_name, []).extend(copied)
                    else:
                        if src_item.is_file():
                            try:
                                dst_item.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(src_item, dst_item)
                                extra_new.setdefault(item_name, []).append(item_name)
                            except Exception as e:
                                logger.error("Copy failed %s -> %s: %s", src_item, dst_item, e)
                self._pending_transfer_new_files = extra_new
                bus.done.emit(mods_summary)
            except Exception as e:
                logger.exception("Transfer worker failed: %s", e)
                self._pending_transfer_new_files = extra_new
                bus.done.emit(mods_summary)
        threading.Thread(target=worker, daemon=True).start()

    def _on_transfer_progress(self, p, _unused=0.0):
        if isinstance(p, TransferProgress) and p.phase == 'resolve':
            self.update_ui_progress(
                self.tr("analysis_progress", name=p.current_name, done=p.done, total=p.total),
                0.5 * p.percent)
        elif isinstance(p, TransferProgress) and p.phase == 'copy':
            self.update_ui_progress(
                self.tr("copy_progress", label=p.current_name, done=p.done, total=p.total),
                p.percent)
        elif isinstance(p, TransferProgress):
            self.update_ui_progress(
                self.tr("download_progress", name=p.current_name, done=p.done, total=p.total),
                0.5 + 0.5 * p.percent)
        else:
            self.update_ui_progress(str(p), float(_unused or 0.0))

    def _on_transfer_done(self, summary: Optional[TransferSummary], dst_path: Path):
        self._end_cancel(self.btn_cancel_transfer, key="transfer")
        extra = getattr(self, "_pending_transfer_new_files", {}) or {}
        self._pending_transfer_new_files = {}
        if summary is not None:
            self._render_transfer_summary(summary)
            if self._last_backup_dir is not None:
                self._append_new_files_to_manifest(summary, dst_path, extra)
        else:
            # No mods phase: still record file copies for rollback.
            if self._last_backup_dir is not None and extra:
                self._append_new_files_to_manifest(None, dst_path, extra)
            cancelled = False
            self.update_ui_progress(self.tr("transfer_files_done"), 1.0)
            self.set_status(self.tr("transfer_files_done"), "ok")
        self._set_transfer_busy(False)
        self._set_backup_button_state()
        if summary is not None and summary.ok > 0:
            QTimer.singleShot(2500, lambda: self.set_status(self.tr("transfer_reminder")))

    def _append_new_files_to_manifest(
        self,
        summary: Optional[TransferSummary],
        dst_path: Path,
        extra_new: Optional[Dict[str, List[str]]] = None,
    ):
        if self._last_backup_dir is None:
            return
        manifest_path = self._last_backup_dir / "manifest.json"
        if not manifest_path.exists():
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Cannot read manifest: %s", e)
            return
        items = data.setdefault("items", {})

        def _ensure_item(name: str) -> dict:
            item = items.setdefault(name, {"name": name, "policy": "intersection",
                                           "backed_up": [], "new_files": []})
            item.setdefault("backed_up", [])
            new_list = item.setdefault("new_files", [])
            return item

        def _add_new(item_name: str, rel: str):
            item = _ensure_item(item_name)
            if rel not in item["new_files"]:
                item["new_files"].append(rel)

        if summary is not None:
            for r in summary.results:
                if r.status == SingleResultStatus.OK and r.mod_info:
                    filename = r.mod_info.get('filename')
                    if filename:
                        # Sanitize: manifest paths must stay inside profile.
                        safe = Path(filename).name
                        if safe:
                            _add_new("mods", f"mods/{safe}")
        for item_name, rels in (extra_new or {}).items():
            for rel in rels:
                # extra rels are already "item/..." or bare filenames.
                rel_norm = rel.replace("\\", "/")
                if rel_norm == item_name or "/" not in rel_norm:
                    rel_norm = f"{item_name}/{Path(rel_norm).name}"
                # Refuse escapes.
                if ".." in Path(rel_norm).parts:
                    continue
                _add_new(item_name, rel_norm)
        # Atomic write: tmp + replace.
        try:
            tmp_path = manifest_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(manifest_path)
        except Exception as e:
            logger.error("Cannot write manifest: %s", e)

    def copy_folder(self, src: Path, dst: Path, item_name: str = None,
                    bus: Optional[BusSignals] = None,
                    cancel_event: Optional[threading.Event] = None) -> List[str]:
        """Copy folder/file; return profile-relative paths of written files."""
        policy = DEFAULT_POLICY.get(item_name, BACKUP_INTERSECTION) if item_name else BACKUP_INTERSECTION
        written: List[str] = []
        prefix = item_name or dst.name
        try:
            if src.is_dir():
                files = [p for p in src.rglob("*") if p.is_file()]
                total = len(files)
                if total == 0:
                    dst.mkdir(parents=True, exist_ok=True)
                    return written
                copied = 0
                skipped = 0
                for p in files:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    try:
                        rel = p.relative_to(src)
                    except ValueError:
                        continue
                    # Refuse suspicious rels.
                    if ".." in rel.parts or rel.is_absolute():
                        continue
                    target = dst / rel
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        logger.error("Copy mkdir failed %s: %s", target.parent, e)
                        continue
                    if policy == BACKUP_SKIP and target.exists():
                        skipped += 1
                    else:
                        try:
                            shutil.copy2(p, target)
                            copied += 1
                            written.append(f"{prefix}/{rel.as_posix()}")
                        except Exception as e:
                            logger.error("Copy failed %s -> %s: %s", p, target, e)
                    if bus is not None and (copied % 5 == 0 or (copied + skipped) == total):
                        label = item_name or self.tr("folder")
                        bus.progress.emit(TransferProgress(
                            done=copied + skipped, total=total,
                            current_name=label, phase='copy'), 0.0)
                for p in src.rglob("*"):
                    if p.is_dir():
                        try:
                            (dst / p.relative_to(src)).mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
            elif src.is_file():
                if policy == BACKUP_SKIP and dst.exists():
                    return written
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                written.append(f"{prefix}/{dst.name}" if "/" not in prefix else dst.name)
        except Exception as e:
            logger.error("Copy failed %s -> %s: %s", src, dst, e)
        return written

    # -- analysis cards -- #

    def add_analysis_card(self, info: dict):
        frame, lay = self._card("ok")
        icon = self._icon_label()
        lay.addWidget(icon)
        if info.get('icon_url'):
            self.load_icon(info['icon_url'], icon)
        box = QVBoxLayout()
        n = QLabel(info.get('name', '?'))
        n.setFont(_qfont(FONTS["section"]))
        box.addWidget(n)
        subtitle = f"v{info.get('version_number', '?')}"
        authors = info.get('authors') or []
        if authors:
            subtitle += f"  ·  {', '.join(authors)}"
        if info.get('slug'):
            subtitle += f"  ·  slug: {info['slug']}"
        s = QLabel(subtitle)
        s.setObjectName("muted")
        s.setWordWrap(True)
        box.addWidget(s)
        lay.addLayout(box, 1)
        self.analysis_list_ok.insertWidget(self.analysis_list_ok.count() - 1, frame)
        self._scroll_to_bottom(self.analysis_scroll_ok)

    def add_error_analysis_card(self, error_text: str):
        frame, lay = self._card("err")
        lbl = QLabel(f"• {error_text}")
        lbl.setObjectName("error")
        lbl.setWordWrap(True)
        lay.addWidget(lbl, 1)
        self.analysis_list_err.insertWidget(self.analysis_list_err.count() - 1, frame)
        self._scroll_to_bottom(self.analysis_scroll_err)

    def _render_transfer_summary(self, summary: TransferSummary):
        for r in summary.results:
            if r.status == SingleResultStatus.OK and r.mod_info:
                self.add_analysis_card(r.mod_info)
            elif r.status == SingleResultStatus.NO_VERSION:
                name = (r.mod_info or {}).get('name') or r.jar_name
                self.add_error_analysis_card(f"{name}: {r.error or self.tr('no_version_default')}")
            elif r.status == SingleResultStatus.AUTHOR_MISMATCH:
                name = (r.mod_info or {}).get('name') or r.jar_name
                self.add_error_analysis_card(f"{name}: {r.error or self.tr('author_mismatch_default')}")
            elif r.status == SingleResultStatus.AMBIGUOUS:
                self.add_ambiguous_analysis_card(r.jar_name, r.candidates or [], r.dst_folder)
            elif r.status == SingleResultStatus.RATE_LIMITED:
                self._add_rate_limited_analysis_card(r.jar_name)
            elif r.status == SingleResultStatus.DOWNLOAD_ERROR:
                name = (r.mod_info or {}).get('name') or r.jar_name
                self.add_error_analysis_card(self.tr("analysis_download_error", name=name))
            elif r.status == SingleResultStatus.READ_ERROR:
                self.add_error_analysis_card(self.tr("analysis_read_error", name=r.jar_name))
            else:
                self.add_error_analysis_card(self.tr("analysis_unresolved", name=r.jar_name))
        final = (self.tr("transfer_cancelled", ok=summary.ok, total=summary.total)
                 if summary.cancelled else self.tr("transfer_done", ok=summary.ok, total=summary.total))
        self.update_ui_progress(final, 1.0)
        self.set_status(final, "ok" if summary.ok else "error")
        self.analysis_tabs.setCurrentIndex(0 if summary.ok else 1)

    def _add_rate_limited_analysis_card(self, name: str):
        frame, lay = self._card("warn")
        lbl = QLabel(self.tr("card_rate_limited_short", name=name))
        lbl.setWordWrap(True)
        lay.addWidget(lbl, 1)
        self.analysis_list_err.insertWidget(self.analysis_list_err.count() - 1, frame)
        self._scroll_to_bottom(self.analysis_scroll_err)

    def add_ambiguous_analysis_card(self, name: str, candidates: list, dst_mods_folder=None):
        frame = QFrame()
        frame.setObjectName("card-info")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(frame)
        title = QLabel(self.tr("card_ambiguous_short", name=name))
        title.setWordWrap(True)
        lay.addWidget(title)
        for c in candidates[:5]:
            row = QHBoxLayout()
            authors = ", ".join(c.get('authors') or []) or "—"
            dl = f"{c.get('downloads', 0):,}".replace(",", " ")
            lbl = QLabel(f"   • {c.get('name')}  ·  {authors}  ·  {self.tr('downloads', n=dl)}")
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            if dst_mods_folder is not None:
                btn = QPushButton(self.tr("select"))
                btn.setObjectName("primary")
                btn.clicked.connect(
                    lambda _=False, cid=c['project_id'], nm=name, dst=dst_mods_folder, card=frame:
                        self._pick_analysis_candidate(cid, nm, dst, card))
                row.addWidget(btn)
            lay.addLayout(row)
        self.analysis_list_err.insertWidget(self.analysis_list_err.count() - 1, frame)
        self._scroll_to_bottom(self.analysis_scroll_err)

    def _pick_analysis_candidate(self, project_id: str, original_name: str,
                                 dst_mods_folder: Path, card=None):
        if card is not None:
            card.deleteLater()
        version = self.cmb_version.currentText().strip()
        loader = self.cmb_loader.currentText().strip()
        bus = BusSignals()
        bus.done.connect(lambda res: self._on_analysis_candidate(res, original_name))

        def worker():
            result = self.api.resolve_by_project_id(project_id, version, loader)
            if result.get('status') == STATUS_FOUND:
                try:
                    filename = sanitize_filename(result.get('filename') or f"{project_id}.jar")
                    result['filename'] = filename
                    dst_mods_folder.mkdir(parents=True, exist_ok=True)
                    ok, err = download_url_to_file(
                        result.get('download_url', ''), dst_mods_folder / filename,
                        session=getattr(self.api, 'session', None),
                        timeout=30,
                        expected_sha1=result.get('file_sha1'),
                        expected_size=result.get('file_size'),
                    )
                    if not ok:
                        result = {'status': 'download_error', 'name': result.get('name'),
                                  'error': err}
                except Exception as e:
                    logger.exception("Failed to download %s", result.get('name'))
                    result = {'status': 'download_error', 'name': result.get('name'),
                              'error': str(e)}
            bus.done.emit(result)
        threading.Thread(target=worker, daemon=True).start()

    def _on_analysis_candidate(self, result: dict, original_name: str):
        status = result.get('status')
        if status == STATUS_FOUND:
            self.add_analysis_card(result)
            self.set_status(self.tr("downloaded", name=result.get('name')), "ok")
        elif status == STATUS_NO_VERSION:
            self.add_error_analysis_card(
                f"{result.get('name') or original_name}: "
                f"{result.get('reason', self.tr('no_version_default'))}")
        elif status == 'download_error':
            self.add_error_analysis_card(self.tr(
                "analysis_download_error_detail",
                name=result.get('name') or original_name, error=result.get('error')))
        else:
            self.add_error_analysis_card(self.tr("analysis_resolve_fail", name=original_name))


def resource_path(*parts: str) -> Path:
    """Resource path: next to the code, or sys._MEIPASS (PyInstaller onefile)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return base.joinpath(*parts)


def app_icon() -> "QIcon":
    """App icon (assets/icon.png); null when the file is missing."""
    from PySide6.QtGui import QIcon as _QIcon
    p = resource_path("assets", "icon.png")
    try:
        if p.exists():
            return _QIcon(str(p))
    except Exception as e:
        logger.debug("Icon failed to load: %s", e)
    return _QIcon()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ModBridge")
    app.setWindowIcon(app_icon())  # window title bar + taskbar / dock
    if sys.platform == "win32":
        # Explicit AppUserModelID so the taskbar groups the exe/script
        # under its own icon instead of generic "Python".
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Woolfin.ModBridge")
        except Exception as e:
            logger.debug("AppUserModelID failed: %s", e)
    win = App()
    win.show()
    return app.exec()
