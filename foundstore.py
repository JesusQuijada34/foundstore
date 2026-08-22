#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from threading import Event
from typing import Any, Callable

import requests
from PyQt6.QtCore import QRect, QRectF, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import fluthin_manager as manager
import foundstore_api
from foundstore_preferences import ACCENTS, FoundstorePreferences

try:
    from leviathan_ui import WipeWindow
except Exception:
    WipeWindow = None


ROOT = Path(__file__).resolve().parent
ACCENT = "#77e9b2"
INK = "#edf3ff"
MUTED = "#9daac2"
IMAGE_BYTES_CACHE: dict[str, bytes] = {}


def package_reference(package: dict[str, Any]) -> str:
    author = str(package.get("author") or "").strip()
    app = str(package.get("app") or package.get("slug") or "").strip()
    return f"{author}/{app}" if author and app else ""


def brand_pixmap(size: int) -> QPixmap:
    source = QPixmap(str(ROOT / "static" / "logo_foundstore_transparent.png"))
    if source.isNull():
        return QPixmap()
    return source.copy(QRect(260, 190, 740, 740)).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def soft_shadow(widget: QWidget, alpha: int = 68, blur: int = 26, y_offset: int = 10) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(shadow)


def grid_metrics(available: int, view_mode: str, requested_columns: int) -> tuple[int, int, int]:
    """Devuelve columnas efectivas, anchura de ficha y separación sin permitir desbordamiento."""
    minimum = {"compact": 150, "measured": 170, "macos": 190}[view_mode]
    spacing = {"compact": 8, "measured": 12, "macos": 16}[view_mode]
    columns = min(requested_columns, max(1, max(1, available) // minimum))
    width = max(1, (max(1, available) - spacing * (columns - 1)) // columns)
    return columns, width, spacing


class CatalogWorker(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, force: bool = False) -> None:
        super().__init__()
        self.force = force

    def run(self) -> None:
        try:
            self.loaded.emit(foundstore_api.catalog(force=self.force))
        except Exception as error:
            self.failed.emit(str(error))


class DetailWorker(QThread):
    loaded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, slug: str) -> None:
        super().__init__()
        self.slug = slug

    def run(self) -> None:
        try:
            self.loaded.emit(foundstore_api.package_detail(self.slug))
        except Exception as error:
            self.failed.emit(str(error))


class PackageStateWorker(QThread):
    loaded = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, reference: str) -> None:
        super().__init__()
        self.reference = reference

    def run(self) -> None:
        try:
            installed = manager.installed_record(self.reference)
            update = manager.update_available(self.reference) if installed else None
            self.loaded.emit(installed, update)
        except Exception as error:
            self.failed.emit(str(error))


class PackageActionWorker(QThread):
    stage = pyqtSignal(str)
    completed = pyqtSignal(str)
    cancelled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, action: str, reference: str) -> None:
        super().__init__()
        self.action = action
        self.reference = reference
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            if self.action == "install":
                self.stage.emit("Descargando y validando el release…")
                manager.install(self.reference, cancel_event=self.cancel_event)
            elif self.action == "update":
                self.stage.emit("Buscando e instalando el release nuevo…")
                manager.upgrade(self.reference, cancel_event=self.cancel_event)
            elif self.action == "uninstall":
                self.stage.emit("Retirando los archivos instalados…")
                manager.uninstall(self.reference)
            else:
                raise ValueError("Acción de paquete no reconocida")
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.completed.emit(self.action)
        except manager.InstallationCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class ImageWorker(QThread):
    loaded = pyqtSignal(bytes)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        if not self.url:
            return
        cached = IMAGE_BYTES_CACHE.get(self.url)
        if cached:
            self.loaded.emit(cached)
            return
        try:
            response = requests.get(self.url, headers={"User-Agent": "Foundstore-Qt6/1.1"}, timeout=15)
            if response.ok and len(response.content) <= 8_000_000:
                IMAGE_BYTES_CACHE[self.url] = response.content
                self.loaded.emit(response.content)
        except requests.RequestException:
            return


class RemoteImage(QLabel):
    def __init__(self, url: str, fallback: str, size: QSize, radius: int) -> None:
        super().__init__(fallback)
        self._source: QPixmap | None = None
        self._radius = radius
        self.setObjectName("remoteImage")
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"QLabel#remoteImage{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7a83ef,stop:1 #17243d);"
            f"border:1px solid rgba(225,239,255,.3);border-radius:{radius}px;color:white;font-size:24px;font-weight:850;}}"
        )
        self.worker: ImageWorker | None = None
        if url:
            self.worker = ImageWorker(url)
            self.worker.loaded.connect(self._set_image)
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker.start()

    def _set_image(self, raw: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(raw):
            self._source = pixmap
            self.setText("")
            self._update_pixmap()

    def _update_pixmap(self) -> None:
        self.update()

    def paintEvent(self, event: Any) -> None:
        if self._source is None:
            super().paintEvent(event)
            return
        target = self.rect()
        source = self._source.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = (target.width() - source.width()) // 2
        y = (target.height() - source.height()) // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(target.adjusted(0, 0, -1, -1)), self._radius, self._radius)
        painter.setClipPath(clip)
        painter.drawPixmap(x, y, source)
        painter.setClipping(False)
        painter.setPen(QColor(235, 244, 255, 84))
        painter.drawRoundedRect(target.adjusted(0, 0, -1, -1), self._radius, self._radius)
        painter.end()


class PackageGlyph(RemoteImage):
    def __init__(self, package: dict[str, Any], size: int = 70) -> None:
        visuals = package.get("visuals") if isinstance(package.get("visuals"), dict) else {}
        icon_url = str(visuals.get("icon") or package.get("packageIcon") or "")
        fallback = str(package.get("name") or package.get("app") or "F")[:1].upper()
        super().__init__(icon_url, fallback, QSize(size, size), 14)
        soft_shadow(self, alpha=78, blur=18, y_offset=7)


class WindowDot(QToolButton):
    def __init__(self, color: str, tooltip: str, callback: Callable[[], None]) -> None:
        super().__init__()
        self.setToolTip(tooltip)
        self.setFixedSize(13, 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QToolButton{{background:{color};border:1px solid rgba(0,0,0,.16);border-radius:6px;padding:0}}"
            f"QToolButton:hover{{background:{color};border:2px solid rgba(255,255,255,.7)}}"
        )
        self.clicked.connect(callback)


class PackageBanner(QWidget):
    """Miniatura de la ficha: portada, icono y bloque de identidad dentro del mismo recurso."""

    def __init__(self, package: dict[str, Any], width: int, view_mode: str, detail: bool = False) -> None:
        super().__init__()
        aspect = 0.50 if view_mode == "compact" else 0.54 if view_mode == "measured" else 9 / 16
        height = max(96, round(width * aspect))
        identity_height = 96 if detail else (72 if width >= 300 else 58 if width >= 220 else 50)
        icon_size = 72 if detail else (50 if width >= 300 else 42 if width >= 220 else 34)
        self.setFixedSize(width, height)
        visuals = package.get("visuals") if isinstance(package.get("visuals"), dict) else {}
        splash_url = str(visuals.get("splash") or visuals.get("portrait") or "")
        self.cover = RemoteImage(splash_url, "Vista previa", QSize(width, height), 10)
        self.cover.setParent(self)
        self.cover.move(0, 0)

        identity = QFrame(self.cover)
        identity.setObjectName("bannerIdentity")
        identity.setGeometry(0, height - identity_height, width, identity_height)
        identity.setStyleSheet(
            "QFrame#bannerIdentity{background:rgba(10,18,33,.88);border:0;border-bottom-left-radius:10px;border-bottom-right-radius:10px;}"
        )
        layout = QHBoxLayout(identity)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        layout.addWidget(PackageGlyph(package, icon_size), 0, Qt.AlignmentFlag.AlignVCenter)

        copy = QVBoxLayout()
        copy.setSpacing(1)
        title = QLabel(str(package.get("name") or package.get("app") or "Paquete Fluthin"))
        title.setObjectName("bannerTitle")
        title.setWordWrap(True)
        publisher = QLabel(f"{package.get('publisher') or 'Influent'} · {package.get('author') or 'Autor no informado'}")
        publisher.setObjectName("bannerMeta")
        stars = package.get("stars")
        stars_label = QLabel(f"★ {stars} estrellas GitHub" if isinstance(stars, int) else "★ Estrellas GitHub no disponibles")
        stars_label.setObjectName("bannerStars")
        copy.addWidget(title, 1 if detail else 0)
        if width >= 210 or detail:
            copy.addWidget(publisher)
        copy.addWidget(stars_label)
        layout.addLayout(copy, 1)


class PackageResult(QFrame):
    def __init__(self, package: dict[str, Any], show_details: Callable[[dict[str, Any]], None], install: Callable[[dict[str, Any]], None], width: int, view_mode: str, theme: str) -> None:
        super().__init__()
        self.setObjectName("packageResult")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        density = {"compact": (8, 8, 14), "measured": (12, 10, 18), "macos": (16, 12, 21)}[view_mode]
        if theme == "light":
            self.setStyleSheet(
                "QFrame#packageResult{background:#ffffff;border:1px solid #c7d2e2;border-radius:12px;}"
                "QFrame#packageResult:hover{background:#f5f9ff;border-color:#4cae82;}"
            )
        else:
            self.setStyleSheet(
                "QFrame#packageResult{background:rgba(20,30,50,.72);border:1px solid rgba(164,187,228,.21);border-radius:12px;}"
                "QFrame#packageResult:hover{background:rgba(29,43,70,.92);border-color:rgba(119,233,178,.6);}"
            )
        soft_shadow(self, alpha=34 if view_mode == "compact" else 46 if view_mode == "measured" else 58, blur=density[2], y_offset=6 if view_mode == "compact" else 8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(density[0], density[0], density[0], density[0])
        layout.setSpacing(density[1])

        layout.addWidget(PackageBanner(package, width - density[0] * 2, view_mode))

        footer = QHBoxLayout()
        description = QLabel(str(package.get("description") or "Paquete validado en el catálogo público de Foundstore."))
        description.setObjectName("resultDescription")
        description.setWordWrap(True)
        if view_mode != "compact" or width >= 210:
            footer.addWidget(description, 1)
        else:
            footer.addStretch(1)
        open_button = QPushButton("Abrir")
        open_button.setObjectName("secondaryAction")
        open_button.clicked.connect(lambda: show_details(package))
        footer.addWidget(open_button, 0, Qt.AlignmentFlag.AlignBottom)
        install_button = QPushButton("Instalar")
        install_button.setObjectName("primaryAction")
        install_button.clicked.connect(lambda: install(package))
        footer.addWidget(install_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)


class DetailPanel(QFrame):
    def __init__(self, back: Callable[[], None], action: Callable[[str, dict[str, Any]], None]) -> None:
        super().__init__()
        self._action = action
        self.package: dict[str, Any] | None = None
        self.setObjectName("detailPanel")
        self.setStyleSheet("QFrame#detailPanel{background:rgba(17,26,44,.92);border:1px solid rgba(167,190,230,.22);border-radius:14px;}")
        soft_shadow(self, alpha=65, blur=30, y_offset=12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(14)
        back_button = QPushButton("‹  Volver a resultados")
        back_button.setObjectName("backAction")
        back_button.clicked.connect(back)
        layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignLeft)

        body = QHBoxLayout()
        body.setSpacing(18)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        self.preview_holder = QHBoxLayout()
        left_layout.addLayout(self.preview_holder)
        self.description = QLabel()
        self.description.setObjectName("detailDescription")
        self.description.setWordWrap(True)
        left_layout.addWidget(self.description)

        note = QLabel("La instalación solicita una confirmación local. Foundstore no expone enlaces directos de descarga.")
        note.setObjectName("infoNote")
        note.setWordWrap(True)
        left_layout.addWidget(note)

        self.action_status = QLabel("Comprobando estado local…")
        self.action_status.setObjectName("actionStatus")
        left_layout.addWidget(self.action_status)
        self.progress = QProgressBar()
        self.progress.setObjectName("installProgress")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.hide()
        left_layout.addWidget(self.progress)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.install_button = QPushButton("Instalar")
        self.install_button.setObjectName("primaryAction")
        self.install_button.clicked.connect(lambda: self._request_action("install"))
        self.update_button = QPushButton("Actualizar")
        self.update_button.setObjectName("primaryAction")
        self.update_button.clicked.connect(lambda: self._request_action("update"))
        self.uninstall_button = QPushButton("Desinstalar")
        self.uninstall_button.setObjectName("secondaryAction")
        self.uninstall_button.clicked.connect(lambda: self._request_action("uninstall"))
        self.share_button = QPushButton("Compartir")
        self.share_button.setObjectName("secondaryAction")
        self.share_button.clicked.connect(lambda: self._request_action("share"))
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setObjectName("secondaryAction")
        self.cancel_button.clicked.connect(lambda: self._request_action("cancel"))
        for button in (self.install_button, self.update_button, self.uninstall_button, self.share_button, self.cancel_button):
            actions.addWidget(button)
        actions.addStretch(1)
        left_layout.addLayout(actions)

        right = QFrame()
        right.setObjectName("readmePanel")
        right.setMinimumWidth(360)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(10)
        readme_head = QHBoxLayout()
        readme_label = QLabel("README del paquete")
        readme_label.setObjectName("readmeLabel")
        self.copy_code_button = QPushButton("Copiar código")
        self.copy_code_button.setObjectName("secondaryAction")
        self.copy_code_button.clicked.connect(self.copy_selected_code)
        readme_head.addWidget(readme_label)
        readme_head.addStretch(1)
        readme_head.addWidget(self.copy_code_button)
        right_layout.addLayout(readme_head)

        self.readme = QPlainTextEdit()
        self.readme.setObjectName("readme")
        self.readme.setReadOnly(True)
        self.readme.setMinimumWidth(360)
        self.readme.setMinimumHeight(380)
        right_layout.addWidget(self.readme, 1)
        body.addWidget(left, 1)
        body.addWidget(right, 1)
        layout.addLayout(body)
        self.set_action_state(False, False)

    def apply_theme(self, theme: str) -> None:
        if theme == "light":
            self.setStyleSheet("QFrame#detailPanel{background:#ffffff;border:1px solid #c7d2e2;border-radius:14px;}")
        else:
            self.setStyleSheet("QFrame#detailPanel{background:rgba(17,26,44,.92);border:1px solid rgba(167,190,230,.22);border-radius:14px;}")

    def set_package(self, package: dict[str, Any]) -> None:
        self.package = package
        while self.preview_holder.count():
            item = self.preview_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preview_holder.addWidget(PackageBanner(package, 500, "macos", detail=True))
        self.preview_holder.addStretch(1)
        self.description.setText(str(package.get("description") or "Paquete Fluthin validado en el catálogo público de Foundstore."))
        self.readme.setPlainText(str(package.get("readme") or "Cargando README desde la ficha pública de Foundstore…")[:50_000])

    def set_detail_error(self, message: str) -> None:
        self.readme.setPlainText(f"No se pudo cargar el README público.\n\n{message}")

    def set_action_state(self, installed: bool, update_available: bool, busy: bool = False, status: str = "") -> None:
        self.install_button.setVisible(not installed and not busy)
        self.update_button.setVisible(installed and update_available and not busy)
        self.uninstall_button.setVisible(installed and not busy)
        self.share_button.setVisible(not busy)
        self.cancel_button.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.action_status.setText(status or ("Instalado; hay una actualización disponible" if installed and update_available else "Instalado en este DaneDesk" if installed else "Disponible para instalar"))

    def copy_selected_code(self) -> None:
        selected = self.readme.textCursor().selectedText()
        if not selected:
            self.action_status.setText("Selecciona un bloque de código o texto para copiarlo")
            return
        QApplication.clipboard().setText(selected.replace("\u2029", "\n"))
        self.action_status.setText("Código copiado al portapapeles")

    def _request_action(self, action: str) -> None:
        if self.package:
            self._action(action, self.package)


class StoreWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.preferences = FoundstorePreferences.load()
        self.packages: list[dict[str, Any]] = []
        self.catalog_worker: CatalogWorker | None = None
        self.detail_worker: DetailWorker | None = None
        self.package_state_worker: PackageStateWorker | None = None
        self.package_action_worker: PackageActionWorker | None = None
        self._grid_signature: tuple[int, int, str] | None = None
        self.setWindowTitle("Foundstore")
        self.resize(1220, 790)
        self.setMinimumSize(880, 620)
        self._apply_leviathan()
        self._build_ui()
        self.cache_timer = QTimer(self)
        self.cache_timer.setInterval(60_000)
        self.cache_timer.timeout.connect(self.refresh_if_cache_expired)
        self.cache_timer.start()
        QTimer.singleShot(120, self.initialize_catalog)

    def _apply_leviathan(self) -> None:
        if WipeWindow is not None:
            try:
                WipeWindow.create().set_mode("mica").set_radius(18).apply(self)
            except Exception:
                pass

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.root = root
        root.setStyleSheet(self._stylesheet())
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 18)
        outer.setSpacing(12)
        outer.addLayout(self._title_bar())
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._catalog_page())
        self.pages.addWidget(self._library_page())
        self.pages.addWidget(self._settings_page())
        self.detail = DetailPanel(lambda: self.pages.setCurrentIndex(0), self.request_package_action)
        self.detail.apply_theme(self.preferences.theme)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("detailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.setWidget(self.detail)
        self.pages.addWidget(self.detail_scroll)
        content.addWidget(self.pages, 1)
        outer.addLayout(content, 1)

    def _title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(7, 0, 7, 0)
        dots = QHBoxLayout()
        dots.setSpacing(8)
        dots.addWidget(WindowDot("#ff6b63", "Cerrar", self.close))
        dots.addWidget(WindowDot("#f7c34e", "Minimizar", self.showMinimized))
        dots.addWidget(WindowDot("#56cb84", "Maximizar o restaurar", self._toggle_maximized))
        bar.addLayout(dots)
        bar.addStretch(1)
        title = QLabel("Foundstore para Danenone")
        title.setObjectName("windowTitle")
        bar.addWidget(title)
        bar.addStretch(1)
        status = QLabel("API pública Foundstore")
        status.setObjectName("windowStatus")
        bar.addWidget(status)
        return bar

    def _sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 18, 16, 16)
        sidebar_layout.setSpacing(10)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand_pixmap(38))
        logo.setFixedSize(38, 38)
        brand_title = QLabel("Foundstore")
        brand_title.setObjectName("brandTitle")
        brand.addWidget(logo)
        brand.addWidget(brand_title)
        brand.addStretch(1)
        sidebar_layout.addLayout(brand)
        caption = QLabel("Aplicaciones Fluthin\npara tu DaneDesk")
        caption.setObjectName("sidebarCaption")
        sidebar_layout.addWidget(caption)
        sidebar_layout.addSpacing(10)
        self.nav_buttons: list[QPushButton] = []
        for label, index in (("Descubrir", 0), ("Biblioteca", 1), ("Configuración", 2)):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, page=index: self.switch_page(page))
            self.nav_buttons.append(button)
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch(1)
        connectivity = QLabel("Catálogo, recursos y estrellas\nse consultan desde la API pública.")
        connectivity.setObjectName("sidebarFooter")
        connectivity.setWordWrap(True)
        sidebar_layout.addWidget(connectivity)
        return sidebar

    def _catalog_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(15)
        top = QHBoxLayout()
        copy = QVBoxLayout()
        eyebrow = QLabel("TIENDA FLUTHIN")
        eyebrow.setObjectName("eyebrow")
        headline = QLabel("Encuentra tu siguiente\nexperiencia para DaneDesk.")
        headline.setObjectName("catalogHeadline")
        copy.addWidget(eyebrow)
        copy.addWidget(headline)
        top.addLayout(copy, 1)
        self.catalog_status = QLabel("Preparando catálogo")
        self.catalog_status.setObjectName("catalogStatus")
        top.addWidget(self.catalog_status, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Buscar aplicaciones, autor o descripción")
        self.search.textChanged.connect(self.filter_packages)
        refresh = QPushButton("Actualizar")
        refresh.setObjectName("secondaryAction")
        refresh.clicked.connect(lambda: self.refresh_catalog(force=True))
        tools.addWidget(self.search, 1)
        tools.addWidget(refresh)
        layout.addLayout(tools)
        self.catalog_scroll = QScrollArea()
        self.catalog_scroll.setObjectName("catalogScroll")
        self.catalog_scroll.setWidgetResizable(True)
        self.catalog_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.catalog_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.catalog_grid_host = QWidget()
        self.catalog_grid_host.setObjectName("catalogGridHost")
        self.catalog_grid_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.catalog_grid = QGridLayout(self.catalog_grid_host)
        self.catalog_grid.setContentsMargins(0, 0, 0, 0)
        self.catalog_grid.setHorizontalSpacing(16)
        self.catalog_grid.setVerticalSpacing(16)
        self.catalog_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.catalog_scroll.setWidget(self.catalog_grid_host)
        layout.addWidget(self.catalog_scroll, 1)
        return page

    def _library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 24, 26, 24)
        title = QLabel("Tu biblioteca")
        title.setObjectName("pageTitle")
        copy = QLabel("Las aplicaciones instaladas mediante Foundstore aparecen aquí. El catálogo de la tienda permanece separado del estado local del equipo.")
        copy.setObjectName("pageCopy")
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)
        self.library_list = QListWidget()
        self.library_list.setObjectName("catalogList")
        self.library_list.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.library_list, 1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 24, 26, 24)
        title = QLabel("Configuración")
        title.setObjectName("pageTitle")
        copy = QLabel("Esta aplicación consulta únicamente APIs públicas de Foundstore para navegar. La instalación todavía requiere tu confirmación explícita y una validación local de release.")
        copy.setObjectName("pageCopy")
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)

        appearance = QLabel("Personalización")
        appearance.setObjectName("settingsSection")
        layout.addWidget(appearance)
        self.view_control = self._preference_control(
            "Vista de inicio",
            [("Compacto", "compact"), ("Milimetrado", "measured"), ("MacOS Style", "macos")],
            self.preferences.view_mode,
        )
        self.grid_control = self._preference_control(
            "Fichas horizontales",
            [("3 columnas", 3), ("4 columnas", 4), ("5 columnas", 5)],
            self.preferences.grid_columns,
        )
        self.theme_control = self._preference_control(
            "Modo de la aplicación",
            [("Oscuro", "dark"), ("Claro", "light")],
            self.preferences.theme,
        )
        self.accent_control = self._preference_control(
            "Color de interfaz",
            [("Verdypor", "verdypor"), ("Océano", "oceano"), ("Violeta", "violeta"), ("Coral", "coral"), ("Oro", "oro")],
            self.preferences.accent,
        )
        for control in (self.view_control, self.grid_control, self.theme_control, self.accent_control):
            layout.addWidget(control)
            control.findChild(QComboBox).currentIndexChanged.connect(self.apply_preferences)
        open_web = QPushButton("Abrir Foundstore web")
        open_web.setObjectName("secondaryAction")
        open_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://imfoundstore.onrender.com")))
        layout.addWidget(open_web, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _preference_control(self, title: str, options: list[tuple[str, Any]], selected: Any) -> QFrame:
        frame = QFrame()
        frame.setObjectName("preferenceControl")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        label = QLabel(title)
        label.setObjectName("preferenceLabel")
        combo = QComboBox()
        combo.setObjectName("preferenceCombo")
        for text, value in options:
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        row.addWidget(label, 1)
        row.addWidget(combo)
        return frame

    def apply_preferences(self) -> None:
        self.preferences = FoundstorePreferences(
            theme=str(self.theme_control.findChild(QComboBox).currentData()),
            accent=str(self.accent_control.findChild(QComboBox).currentData()),
            view_mode=str(self.view_control.findChild(QComboBox).currentData()),
            grid_columns=int(self.grid_control.findChild(QComboBox).currentData()),
        )
        self.preferences.save()
        self.root.setStyleSheet(self._stylesheet())
        self.detail.apply_theme(self.preferences.theme)
        self._grid_signature = None
        self.filter_packages(self.search.text())
        if self.detail.package:
            self.detail.set_package(self.detail.package)

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        if index == 1:
            self.refresh_library()

    def initialize_catalog(self) -> None:
        cached = foundstore_api.cached_catalog()
        if cached is None:
            self.refresh_catalog()
            return
        self.packages, is_fresh = cached
        self.catalog_status.setText(
            f"{len(self.packages)} paquetes en caché" if is_fresh else f"{len(self.packages)} paquetes; actualizando…"
        )
        self.filter_packages(self.search.text())
        if not is_fresh:
            self.refresh_catalog()

    def refresh_if_cache_expired(self) -> None:
        cached = foundstore_api.cached_catalog()
        if cached is None or not cached[1]:
            self.refresh_catalog()

    def refresh_catalog(self, force: bool = False) -> None:
        if self.catalog_worker and self.catalog_worker.isRunning():
            return
        self.catalog_status.setText("Actualizando API…")
        self._add_empty_row("Consultando API pública…", "La ventana sigue disponible mientras Foundstore obtiene paquetes, recursos y estrellas verificadas.")
        self.catalog_worker = CatalogWorker(force=force)
        self.catalog_worker.loaded.connect(self._catalog_loaded)
        self.catalog_worker.failed.connect(self._catalog_failed)
        self.catalog_worker.start()

    def _catalog_loaded(self, packages: list[dict[str, Any]]) -> None:
        self.packages = packages
        self.catalog_status.setText(f"{len(self.packages)} paquetes verificados")
        self.filter_packages(self.search.text())
        self.catalog_worker = None

    def _catalog_failed(self, message: str) -> None:
        self.catalog_status.setText("API no disponible")
        self._add_empty_row("No se pudo consultar la API pública", message)
        self.catalog_worker = None

    def filter_packages(self, query: str) -> None:
        term = query.casefold().strip()
        visible = [
            package for package in self.packages
            if not term or term in " ".join(str(package.get(key) or "") for key in ("name", "app", "author", "description", "platform", "category")).casefold()
        ]
        self._clear_catalog_grid()
        if not visible:
            self._add_empty_row("No hay resultados", "Prueba otra búsqueda o actualiza la API pública.")
            return
        available = max(1, self.catalog_scroll.viewport().width() - 2)
        columns, card_width, spacing = grid_metrics(available, self.preferences.view_mode, self.preferences.grid_columns)
        self.catalog_grid.setHorizontalSpacing(spacing)
        self.catalog_grid.setVerticalSpacing(spacing)
        self._grid_signature = (card_width, columns, self.preferences.view_mode)
        for index, package in enumerate(visible):
            widget = PackageResult(package, self.show_detail, self.install_package, card_width, self.preferences.view_mode, self.preferences.theme)
            self.catalog_grid.addWidget(widget, index // columns, index % columns)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self.packages:
            QTimer.singleShot(0, lambda: self.filter_packages(self.search.text()))

    def _clear_catalog_grid(self) -> None:
        while self.catalog_grid.count():
            item = self.catalog_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_empty_row(self, title: str, detail: str) -> None:
        self._clear_catalog_grid()
        widget = QFrame()
        widget.setObjectName("emptyState")
        layout = QVBoxLayout(widget)
        headline = QLabel(title)
        headline.setObjectName("emptyTitle")
        copy = QLabel(detail)
        copy.setObjectName("pageCopy")
        copy.setWordWrap(True)
        layout.addWidget(headline)
        layout.addWidget(copy)
        self.catalog_grid.addWidget(widget, 0, 0)

    def show_detail(self, package: dict[str, Any]) -> None:
        self.detail.set_package(package)
        self.refresh_package_state(package)
        self.pages.setCurrentWidget(self.detail_scroll)
        for button in self.nav_buttons:
            button.setChecked(False)
        slug = str(package.get("slug") or package.get("app") or "")
        if not slug:
            return
        self.detail_worker = DetailWorker(slug)
        self.detail_worker.loaded.connect(self._detail_loaded)
        self.detail_worker.failed.connect(self._detail_failed)
        self.detail_worker.start()

    def _detail_loaded(self, package: dict[str, Any]) -> None:
        self.detail.set_package(package)
        self.detail_worker = None

    def _detail_failed(self, message: str) -> None:
        self.detail.set_detail_error(message)
        self.detail_worker = None

    def refresh_package_state(self, package: dict[str, Any]) -> None:
        reference = package_reference(package)
        if not reference or (self.package_state_worker and self.package_state_worker.isRunning()):
            return
        self.detail.set_action_state(False, False, status="Comprobando instalación y actualizaciones…")
        self.package_state_worker = PackageStateWorker(reference)
        self.package_state_worker.loaded.connect(self._package_state_loaded)
        self.package_state_worker.failed.connect(self._package_state_failed)
        self.package_state_worker.start()

    def _package_state_loaded(self, installed: object, update: object) -> None:
        self.detail.set_action_state(installed is not None, update is not None)
        self.package_state_worker = None

    def _package_state_failed(self, message: str) -> None:
        self.detail.set_action_state(False, False, status="No se pudo comprobar el estado local")
        self.package_state_worker = None

    def request_package_action(self, action: str, package: dict[str, Any]) -> None:
        reference = package_reference(package)
        if not reference:
            self.detail.set_action_state(False, False, status="El paquete no contiene una referencia válida")
            return
        if action == "share":
            author, app = reference.split("/", 1)
            QApplication.clipboard().setText(f"https://imfoundstore.onrender.com/{author}/{app}/")
            self.detail.set_action_state(False, False, status="Enlace de ficha copiado al portapapeles")
            return
        if action == "cancel":
            if self.package_action_worker and self.package_action_worker.isRunning():
                self.package_action_worker.cancel()
                self.detail.set_action_state(False, False, True, "Cancelando la operación…")
            return
        if self.package_action_worker and self.package_action_worker.isRunning():
            return
        labels = {"install": "instalar", "update": "actualizar", "uninstall": "desinstalar"}
        answer = QMessageBox.question(
            self,
            "Confirmar acción",
            f"¿Deseas {labels[action]} {package.get('name') or package.get('app')}?\n\n"
            "Foundstore validará los artefactos compatibles y no ejecutará código del paquete durante esta operación.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.detail.set_action_state(False, False, True, f"Preparando para {labels[action]}…")
        self.package_action_worker = PackageActionWorker(action, reference)
        self.package_action_worker.stage.connect(lambda message: self.detail.set_action_state(False, False, True, message))
        self.package_action_worker.completed.connect(lambda completed: self._package_action_completed(completed, package))
        self.package_action_worker.cancelled.connect(lambda: self._package_action_cancelled(package))
        self.package_action_worker.failed.connect(lambda message: self._package_action_failed(message, package))
        self.package_action_worker.start()

    def _package_action_completed(self, action: str, package: dict[str, Any]) -> None:
        self.package_action_worker = None
        self.refresh_library()
        self.refresh_package_state(package)
        self.detail.action_status.setText({"install": "Instalación completada", "update": "Actualización completada", "uninstall": "Paquete desinstalado"}[action])

    def _package_action_cancelled(self, package: dict[str, Any]) -> None:
        self.package_action_worker = None
        self.refresh_package_state(package)
        self.detail.action_status.setText("Operación cancelada")

    def _package_action_failed(self, message: str, package: dict[str, Any]) -> None:
        self.package_action_worker = None
        self.refresh_package_state(package)
        self.detail.action_status.setText(f"No se pudo completar la operación: {message}")

    def refresh_library(self) -> None:
        self.library_list.clear()
        installed = manager.installed()
        if not installed:
            self.library_list.addItem(QListWidgetItem("Aún no hay aplicaciones instaladas desde Foundstore."))
            return
        for record in installed:
            metadata = record.get("metadata", {})
            self.library_list.addItem(QListWidgetItem(f"{metadata.get('name', metadata.get('app', 'Fluthin'))}\n{metadata.get('version', '')}"))

    def install_package(self, package: dict[str, Any]) -> None:
        self.request_package_action("install", package)

    def _stylesheet(self) -> str:
        accent = self.preferences.accent_color
        if self.preferences.theme == "light":
            root_background = "#eef3f8"
            surface = "#ffffff"
            panel = "#f7faff"
            border = "#c8d3e0"
            ink = "#172338"
            muted = "#5a6880"
            heading = "#162238"
            button = "#eef3f9"
            button_hover = "#dde8f6"
            note = "#e5f6ee"
            note_ink = "#256448"
            code_background = "#f1f5f9"
        else:
            root_background = "#101c31"
            surface = "rgba(17,26,44,.92)"
            panel = "rgba(12,20,34,.74)"
            border = "rgba(158,183,226,.22)"
            ink = INK
            muted = MUTED
            heading = "#f3f7ff"
            button = "rgba(28,40,65,.7)"
            button_hover = "rgba(61,83,126,.8)"
            note = "rgba(25,91,70,.24)"
            note_ink = "#b8f2d3"
            code_background = "rgba(7,13,24,.62)"
        return f"""
            QWidget#root {{background:{root_background};color:{ink};font-family:Inter,Segoe UI,Arial,sans-serif;}}
            QLabel#windowTitle {{font-size:13px;font-weight:750;color:{heading};}} QLabel#windowStatus {{font-size:11px;font-weight:700;color:{accent};}}
            QFrame#sidebar {{background:{panel};border:1px solid {border};border-radius:14px;}} QLabel#brandTitle {{font-size:19px;font-weight:850;letter-spacing:-.04em;color:{heading};}} QLabel#sidebarCaption,QLabel#sidebarFooter {{color:{muted};font-size:12px;line-height:1.45;}}
            QPushButton#navButton {{background:transparent;border:1px solid transparent;border-radius:8px;color:{muted};padding:10px 12px;text-align:left;font-weight:700;}} QPushButton#navButton:hover,QPushButton#navButton:checked {{background:{button_hover};border-color:{border};color:{heading};}}
            QLabel#eyebrow,QLabel#resultCategory {{color:{accent};font-size:10px;font-weight:850;letter-spacing:.12em;}} QLabel#catalogHeadline {{color:{heading};font-size:31px;font-weight:850;letter-spacing:-.05em;line-height:1.02;}} QLabel#catalogStatus {{background:{button};border:1px solid {border};border-radius:8px;color:{muted};padding:8px 10px;font-size:11px;font-weight:700;}}
            QLineEdit#search,QComboBox#preferenceCombo {{background:{surface};border:1px solid {border};border-radius:8px;color:{ink};padding:10px 12px;font-size:13px;}} QLineEdit#search:focus,QComboBox#preferenceCombo:focus {{border:2px solid {accent};padding:9px 11px;}}
            QListWidget#catalogList,QScrollArea#detailScroll,QScrollArea#catalogScroll {{background:transparent;outline:none;}} QListWidget#catalogList::item {{background:transparent;border:0;}} QWidget#catalogGridHost {{background:transparent;}} QFrame#emptyState,QFrame#preferenceControl {{background:{surface};border:1px solid {border};border-radius:10px;padding:10px;min-width:420px;}} QLabel#emptyTitle,QLabel#preferenceLabel,QLabel#settingsSection {{color:{heading};font-size:16px;font-weight:800;}}
            QLabel#resultDescription,QLabel#pageCopy {{color:{muted};font-size:12px;line-height:1.42;}} QLabel#resultStars,QLabel#detailStars,QLabel#bannerStars {{color:{accent};font-size:11px;font-weight:800;}} QLabel#bannerTitle {{color:#f4f8ff;font-size:13px;font-weight:850;}} QLabel#bannerMeta {{color:#bdcbe1;font-size:10px;}}
            QLabel#actionStatus {{color:{muted};font-size:12px;font-weight:700;}}
            QFrame#detailPanel {{min-width:0;}} QLabel#detailTitle,QLabel#pageTitle {{color:{heading};font-size:30px;font-weight:850;letter-spacing:-.045em;}} QLabel#detailDescription {{color:{muted};font-size:15px;line-height:1.55;}} QLabel#readmeLabel {{color:{heading};font-size:13px;font-weight:850;}} QPlainTextEdit#readme {{background:{code_background};border:1px solid {border};border-radius:10px;color:{ink};padding:10px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;}} QLabel#infoNote {{background:{note};border:1px solid {accent};border-radius:10px;color:{note_ink};padding:13px;font-size:12px;line-height:1.48;}}
            QFrame#readmePanel {{background:{button};border:1px solid {border};border-radius:12px;}} QProgressBar#installProgress {{background:{button};border:1px solid {border};border-radius:4px;min-height:6px;max-height:6px;}} QProgressBar#installProgress::chunk {{background:{accent};border-radius:3px;}}
            QPushButton#primaryAction {{background:{accent};border:1px solid {accent};border-radius:8px;color:#082218;padding:9px 13px;font-size:12px;font-weight:850;}} QPushButton#primaryAction:hover {{background:{accent};border:2px solid {heading};padding:8px 12px;}} QPushButton#secondaryAction,QPushButton#backAction {{background:{button};border:1px solid {border};border-radius:8px;color:{heading};padding:9px 12px;font-size:12px;font-weight:750;}} QPushButton#secondaryAction:hover,QPushButton#backAction:hover {{background:{button_hover};border-color:{accent};}} QPushButton:disabled {{color:{muted};background:{button};border-color:{border};}}
            QPushButton:focus-visible,QLineEdit:focus-visible,QComboBox:focus-visible {{outline:2px solid {accent};outline-offset:2px;}}
        """


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Foundstore")
    app.setOrganizationName("Influent")
    icon_path = ROOT / "static" / "logo_foundstore_transparent.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = StoreWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
