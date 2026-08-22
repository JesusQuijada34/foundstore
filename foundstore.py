#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import requests
from PyQt6.QtCore import QRect, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import fluthin_manager as manager
import foundstore_api

try:
    from leviathan_ui import WipeWindow
except Exception:
    WipeWindow = None


ROOT = Path(__file__).resolve().parent
ACCENT = "#77e9b2"
INK = "#edf3ff"
MUTED = "#9daac2"


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


class CatalogWorker(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.loaded.emit(foundstore_api.catalog())
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


class ImageWorker(QThread):
    loaded = pyqtSignal(bytes)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        if not self.url:
            return
        try:
            response = requests.get(self.url, headers={"User-Agent": "Foundstore-Qt6/1.1"}, timeout=15)
            if response.ok and len(response.content) <= 8_000_000:
                self.loaded.emit(response.content)
        except requests.RequestException:
            return


class RemoteImage(QLabel):
    def __init__(self, url: str, fallback: str, size: QSize, radius: int) -> None:
        super().__init__(fallback)
        self._source: QPixmap | None = None
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7a83ef,stop:1 #17243d);"
            f"border:1px solid rgba(225,239,255,.3);border-radius:{radius}px;color:white;font-size:24px;font-weight:850;"
        )
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
        if self._source is not None:
            self.setPixmap(
                self._source.scaled(
                    self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                )
            )


class PackageGlyph(RemoteImage):
    def __init__(self, package: dict[str, Any], size: int = 70) -> None:
        visuals = package.get("visuals") if isinstance(package.get("visuals"), dict) else {}
        icon_url = str(visuals.get("icon") or package.get("packageIcon") or "")
        fallback = str(package.get("name") or package.get("app") or "F")[:1].upper()
        super().__init__(icon_url, fallback, QSize(size, size), 18)
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


class PackageResult(QFrame):
    def __init__(self, package: dict[str, Any], show_details: Callable[[dict[str, Any]], None], install: Callable[[dict[str, Any]], None]) -> None:
        super().__init__()
        self.setObjectName("packageResult")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#packageResult{background:rgba(20,30,50,.72);border:1px solid rgba(164,187,228,.21);border-radius:18px;}"
            "QFrame#packageResult:hover{background:rgba(29,43,70,.92);border-color:rgba(119,233,178,.6);}"
        )
        soft_shadow(self, alpha=52, blur=21, y_offset=8)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(14)
        layout.addWidget(PackageGlyph(package), 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(3)
        category = QLabel(str(package.get("category") or package.get("platform") or "Fluthin").upper())
        category.setObjectName("resultCategory")
        title = QLabel(str(package.get("name") or package.get("app") or "Paquete Fluthin"))
        title.setObjectName("resultTitle")
        description = QLabel(str(package.get("description") or "Paquete validado en el catálogo público de Foundstore."))
        description.setObjectName("resultDescription")
        description.setWordWrap(True)
        publisher = str(package.get("publisher") or "Influent")
        meta = QLabel(f"{publisher} · {package.get('author') or 'Autor no informado'} · {package.get('version') or 'Sin versión'}")
        meta.setObjectName("resultMeta")
        stars = package.get("stars")
        stars_label = QLabel(f"★ {stars} estrellas GitHub" if isinstance(stars, int) else "★ Estrellas GitHub no disponibles")
        stars_label.setObjectName("resultStars")
        info.addWidget(category)
        info.addWidget(title)
        info.addWidget(description)
        info.addWidget(meta)
        info.addWidget(stars_label)
        layout.addLayout(info, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        details = QPushButton("Ver ficha")
        details.setObjectName("secondaryAction")
        details.clicked.connect(lambda: show_details(package))
        install_button = QPushButton("Instalar")
        install_button.setObjectName("primaryAction")
        install_button.clicked.connect(lambda: install(package))
        actions.addWidget(details)
        actions.addWidget(install_button)
        layout.addLayout(actions, 0)


class DetailPanel(QFrame):
    def __init__(self, back: Callable[[], None], install: Callable[[dict[str, Any]], None]) -> None:
        super().__init__()
        self._install = install
        self.package: dict[str, Any] | None = None
        self.setObjectName("detailPanel")
        self.setStyleSheet("QFrame#detailPanel{background:rgba(17,26,44,.92);border:1px solid rgba(167,190,230,.22);border-radius:22px;}")
        soft_shadow(self, alpha=65, blur=30, y_offset=12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(14)
        back_button = QPushButton("‹  Volver a resultados")
        back_button.setObjectName("backAction")
        back_button.clicked.connect(back)
        layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignLeft)

        head = QHBoxLayout()
        self.glyph_holder = QVBoxLayout()
        head.addLayout(self.glyph_holder, 0)
        copy = QVBoxLayout()
        self.category = QLabel()
        self.category.setObjectName("resultCategory")
        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.meta = QLabel()
        self.meta.setObjectName("detailMeta")
        self.meta.setWordWrap(True)
        self.stars = QLabel()
        self.stars.setObjectName("detailStars")
        copy.addWidget(self.category)
        copy.addWidget(self.title)
        copy.addWidget(self.meta)
        copy.addWidget(self.stars)
        head.addLayout(copy, 1)
        layout.addLayout(head)

        self.description = QLabel()
        self.description.setObjectName("detailDescription")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.preview_holder = QHBoxLayout()
        layout.addLayout(self.preview_holder)

        note = QLabel("La instalación solicita una confirmación local. Foundstore no expone enlaces directos de descarga.")
        note.setObjectName("infoNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        readme_label = QLabel("README del paquete")
        readme_label.setObjectName("readmeLabel")
        layout.addWidget(readme_label)
        self.readme = QPlainTextEdit()
        self.readme.setObjectName("readme")
        self.readme.setReadOnly(True)
        self.readme.setMinimumHeight(148)
        self.readme.setMaximumHeight(210)
        layout.addWidget(self.readme)

        self.install_button = QPushButton("Instalar en este DaneDesk")
        self.install_button.setObjectName("primaryAction")
        self.install_button.clicked.connect(self._request_install)
        layout.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignLeft)

    def set_package(self, package: dict[str, Any]) -> None:
        self.package = package
        while self.glyph_holder.count():
            item = self.glyph_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.glyph_holder.addWidget(PackageGlyph(package, 94))
        while self.preview_holder.count():
            item = self.preview_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        visuals = package.get("visuals") if isinstance(package.get("visuals"), dict) else {}
        splash_url = str(visuals.get("splash") or visuals.get("portrait") or "")
        self.preview_holder.addWidget(RemoteImage(splash_url, "Vista previa", QSize(440, 168), 16))
        self.preview_holder.addStretch(1)
        self.category.setText(str(package.get("category") or package.get("platform") or "Fluthin").upper())
        self.title.setText(str(package.get("name") or package.get("app") or "Paquete Fluthin"))
        self.meta.setText(
            f"{package.get('publisher') or 'Influent'} · {package.get('author') or 'Autor no informado'}\n"
            f"Versión {package.get('version') or 'No informada'} · {package_reference(package)}"
        )
        stars = package.get("stars")
        self.stars.setText(f"★ {stars} estrellas GitHub verificadas" if isinstance(stars, int) else "★ Estrellas GitHub no disponibles")
        self.description.setText(str(package.get("description") or "Paquete Fluthin validado en el catálogo público de Foundstore."))
        self.readme.setPlainText(str(package.get("readme") or "Cargando README desde la ficha pública de Foundstore…")[:50_000])

    def set_detail_error(self, message: str) -> None:
        self.readme.setPlainText(f"No se pudo cargar el README público.\n\n{message}")

    def _request_install(self) -> None:
        if self.package:
            self._install(self.package)


class StoreWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.packages: list[dict[str, Any]] = []
        self.catalog_worker: CatalogWorker | None = None
        self.detail_worker: DetailWorker | None = None
        self.setWindowTitle("Foundstore")
        self.resize(1220, 790)
        self.setMinimumSize(880, 620)
        self._apply_leviathan()
        self._build_ui()
        QTimer.singleShot(120, self.refresh_catalog)

    def _apply_leviathan(self) -> None:
        if WipeWindow is not None:
            try:
                WipeWindow.create().set_mode("mica").set_radius(18).apply(self)
            except Exception:
                pass

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
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
        self.detail = DetailPanel(lambda: self.pages.setCurrentIndex(0), self.install_package)
        self.pages.addWidget(self.detail)
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
        refresh.clicked.connect(self.refresh_catalog)
        tools.addWidget(self.search, 1)
        tools.addWidget(refresh)
        layout.addLayout(tools)
        self.catalog_list = QListWidget()
        self.catalog_list.setObjectName("catalogList")
        self.catalog_list.setFrameShape(QFrame.Shape.NoFrame)
        self.catalog_list.setSpacing(12)
        self.catalog_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        layout.addWidget(self.catalog_list, 1)
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
        open_web = QPushButton("Abrir Foundstore web")
        open_web.setObjectName("secondaryAction")
        open_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://imfoundstore.onrender.com")))
        layout.addWidget(open_web, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        if index == 1:
            self.refresh_library()

    def refresh_catalog(self) -> None:
        if self.catalog_worker and self.catalog_worker.isRunning():
            return
        self.catalog_status.setText("Actualizando API…")
        self.catalog_list.clear()
        self._add_empty_row("Consultando API pública…", "La ventana sigue disponible mientras Foundstore obtiene paquetes, recursos y estrellas verificadas.")
        self.catalog_worker = CatalogWorker()
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
        self.catalog_list.clear()
        self._add_empty_row("No se pudo consultar la API pública", message)
        self.catalog_worker = None

    def filter_packages(self, query: str) -> None:
        term = query.casefold().strip()
        visible = [
            package for package in self.packages
            if not term or term in " ".join(str(package.get(key) or "") for key in ("name", "app", "author", "description", "platform", "category")).casefold()
        ]
        self.catalog_list.clear()
        if not visible:
            self._add_empty_row("No hay resultados", "Prueba otra búsqueda o actualiza la API pública.")
            return
        for package in visible:
            widget = PackageResult(package, self.show_detail, self.install_package)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 132))
            self.catalog_list.addItem(item)
            self.catalog_list.setItemWidget(item, widget)

    def _add_empty_row(self, title: str, detail: str) -> None:
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
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 112))
        self.catalog_list.addItem(item)
        self.catalog_list.setItemWidget(item, widget)

    def show_detail(self, package: dict[str, Any]) -> None:
        self.detail.set_package(package)
        self.pages.setCurrentWidget(self.detail)
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
        reference = package_reference(package)
        if not reference:
            QMessageBox.warning(self, "Foundstore", "El paquete no contiene una referencia válida para instalar.")
            return
        answer = QMessageBox.question(
            self,
            "Confirmar instalación",
            f"¿Instalar {package.get('name') or package.get('app')} desde el catálogo público?\n\n"
            "Foundstore verificará el release compatible con esta plataforma antes de modificar el equipo.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = manager.install(reference)
            metadata = result["metadata"]
            QMessageBox.information(self, "Instalación completada", f"Se instaló {metadata['name']}\n{metadata['version']}")
            self.refresh_library()
        except Exception as error:
            QMessageBox.warning(self, "No se pudo instalar", str(error))

    @staticmethod
    def _stylesheet() -> str:
        return f"""
            QWidget#root {{background:linear-gradient(135deg,#101c31 0%,#11192a 55%,#0a101c 100%);color:{INK};font-family:Inter,Segoe UI,Arial,sans-serif;}}
            QLabel#windowTitle {{font-size:13px;font-weight:750;color:#dbe6fb;}} QLabel#windowStatus {{font-size:11px;font-weight:700;color:{ACCENT};}}
            QFrame#sidebar {{background:rgba(12,20,34,.74);border:1px solid rgba(158,183,226,.16);border-radius:20px;}} QLabel#brandTitle {{font-size:19px;font-weight:850;letter-spacing:-.04em;color:#f0f5ff;}} QLabel#sidebarCaption {{color:{MUTED};font-size:12px;line-height:1.45;}} QLabel#sidebarFooter {{color:#87a1c5;font-size:11px;line-height:1.5;}}
            QPushButton#navButton {{background:transparent;border:1px solid transparent;border-radius:11px;color:#b7c6df;padding:10px 12px;text-align:left;font-weight:700;}} QPushButton#navButton:hover,QPushButton#navButton:checked {{background:rgba(102,133,193,.25);border-color:rgba(183,207,250,.15);color:#f5f8ff;}}
            QLabel#eyebrow,QLabel#resultCategory {{color:{ACCENT};font-size:10px;font-weight:850;letter-spacing:.12em;}} QLabel#catalogHeadline {{color:#f3f7ff;font-size:31px;font-weight:850;letter-spacing:-.05em;line-height:1.02;}} QLabel#catalogStatus {{background:rgba(21,40,61,.75);border:1px solid rgba(158,184,225,.22);border-radius:11px;color:#b9cbe8;padding:8px 10px;font-size:11px;font-weight:700;}}
            QLineEdit#search {{background:rgba(9,15,27,.66);border:1px solid rgba(165,190,232,.28);border-radius:12px;color:{INK};padding:12px 13px;font-size:13px;}} QLineEdit#search:focus {{border:2px solid {ACCENT};padding:11px 12px;}}
            QListWidget#catalogList {{background:transparent;outline:none;}} QListWidget#catalogList::item {{background:transparent;border:0;}} QFrame#emptyState {{background:rgba(17,27,46,.76);border:1px dashed rgba(165,190,232,.35);border-radius:16px;padding:14px;}} QLabel#emptyTitle {{color:#f1f6ff;font-size:16px;font-weight:800;}}
            QLabel#resultTitle {{font-size:17px;font-weight:800;color:#f5f8ff;}} QLabel#resultDescription,QLabel#pageCopy {{color:{MUTED};font-size:12px;line-height:1.42;}} QLabel#resultMeta {{color:#bfd0e9;font-size:11px;}} QLabel#resultStars,QLabel#detailStars {{color:{ACCENT};font-size:12px;font-weight:800;}}
            QFrame#detailPanel {{min-width:0;}} QLabel#detailTitle,QLabel#pageTitle {{color:#f3f7ff;font-size:30px;font-weight:850;letter-spacing:-.045em;}} QLabel#detailMeta {{color:#b7c7e0;font-size:13px;line-height:1.45;}} QLabel#detailDescription {{color:#d4dff1;font-size:15px;line-height:1.55;}} QLabel#readmeLabel {{color:#dce8fb;font-size:13px;font-weight:850;}} QPlainTextEdit#readme {{background:rgba(7,13,24,.62);border:1px solid rgba(155,180,223,.24);border-radius:13px;color:#c9d6ea;padding:10px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;}} QLabel#infoNote {{background:rgba(25,91,70,.24);border:1px solid rgba(116,237,178,.24);border-radius:13px;color:#b8f2d3;padding:13px;font-size:12px;line-height:1.48;}}
            QPushButton#primaryAction {{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #77e9b2,stop:1 #2eb477);border:1px solid rgba(224,255,240,.55);border-radius:10px;color:#082218;padding:9px 13px;font-size:12px;font-weight:850;}} QPushButton#primaryAction:hover {{background:#9df4c8;}} QPushButton#secondaryAction,QPushButton#backAction {{background:rgba(28,40,65,.7);border:1px solid rgba(170,195,235,.28);border-radius:10px;color:#dbe7fa;padding:9px 12px;font-size:12px;font-weight:750;}} QPushButton#secondaryAction:hover,QPushButton#backAction:hover {{background:rgba(61,83,126,.8);border-color:rgba(173,241,205,.55);}} QPushButton:disabled {{color:#7c8aa3;background:rgba(35,45,65,.55);border-color:rgba(130,147,175,.2);}}
            QPushButton:focus-visible,QLineEdit:focus-visible {{outline:2px solid {ACCENT};outline-offset:2px;}}
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
