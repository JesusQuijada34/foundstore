#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cloud_devices import CloudDevicesClient, CloudDevicesError
import fluthin_manager as manager

try:
    from leviathan_ui import CustomTitleBar, WipeWindow
except Exception:
    CustomTitleBar = None
    WipeWindow = None

ROOT = Path(__file__).resolve().parent


class PackageCard(QFrame):
    def __init__(self, package: dict[str, str], action):
        super().__init__()
        self.package = package
        self.setObjectName("packageCard")
        self.setStyleSheet("QFrame#packageCard{background:rgba(255,255,255,0.10);border:1px solid rgba(255,255,255,0.18);border-radius:14px;} QLabel{color:#e9fff8;} QPushButton{background:#168f83;color:white;border:0;border-radius:8px;padding:8px 14px;} QPushButton:hover{background:#1ca99a;}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        text = QVBoxLayout()
        title = QLabel(package.get("name") or package.get("app", "Fluthin"))
        title.setStyleSheet("font-size:17px;font-weight:700;")
        subtitle = QLabel(f"{package.get('author', '')}/{package.get('app', '')} · {package.get('version', '')}")
        subtitle.setStyleSheet("color:#b9d9d1;font-size:12px;")
        description = QLabel(package.get("description") or "Paquete Fluthin disponible en el catálogo.")
        description.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(subtitle)
        text.addWidget(description)
        layout.addLayout(text, 1)
        action_button = QPushButton("Instalar")
        action_button.clicked.connect(lambda: action(package))
        layout.addWidget(action_button, 0, Qt.AlignmentFlag.AlignVCenter)


class StoreWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Foundstore")
        self.resize(980, 680)
        self.setMinimumSize(760, 520)
        self.packages: list[dict[str, str]] = []
        self.cloud_client = CloudDevicesClient()
        self._apply_leviathan()
        self._build_ui()
        self.refresh_catalog()

    def _apply_leviathan(self):
        if WipeWindow is not None:
            try:
                WipeWindow.create().set_mode("mica").set_radius(14).apply(self)
            except Exception:
                pass

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet("QWidget#root{background:#10191c;} QLabel{color:#e9fff8;} QLineEdit{background:rgba(255,255,255,0.10);border:1px solid rgba(255,255,255,0.25);border-radius:9px;color:#e9fff8;padding:10px;} QLineEdit:focus{border:2px solid #168f83;} QPushButton{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);border-radius:9px;color:#e9fff8;padding:9px 13px;} QPushButton:hover{background:rgba(22,143,131,0.36);}")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(12)
        if CustomTitleBar is not None:
            try:
                layout.addWidget(CustomTitleBar(self, title="Foundstore"))
            except Exception:
                pass
        header = QHBoxLayout()
        title = QLabel("Foundstore")
        title.setStyleSheet("font-size:27px;font-weight:700;color:#e9fff8;")
        header.addWidget(title)
        header.addStretch(1)
        self.status = QLabel("Catálogo listo")
        self.status.setStyleSheet("color:#9ac9bf;")
        header.addWidget(self.status)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar paquetes, autores o aplicaciones")
        self.search.textChanged.connect(self.filter_packages)
        toolbar.addWidget(self.search, 1)
        refresh = QPushButton("Actualizar catálogo")
        refresh.clicked.connect(self.refresh_catalog)
        toolbar.addWidget(refresh)
        website = QPushButton("Abrir tienda web")
        website.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://foundstore.onrender.com")))
        toolbar.addWidget(website)
        cloud = QPushButton("Cloud Devices")
        cloud.clicked.connect(self.show_cloud_devices)
        toolbar.addWidget(cloud)
        layout.addLayout(toolbar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        packages_page = QWidget()
        packages_layout = QVBoxLayout(packages_page)
        packages_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setSpacing(10)
        self.list.setStyleSheet("QListWidget{background:transparent;} QListWidget::item{background:transparent;border:0;}")
        packages_layout.addWidget(self.list)
        self.stack.addWidget(packages_page)

        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(18, 18, 18, 18)
        settings_layout.addWidget(QLabel("Configuración de Foundstore"))
        self.notify_updates = QCheckBox("Notificar actualizaciones de paquetes Fluthin")
        self.notify_updates.setChecked(True)
        settings_layout.addWidget(self.notify_updates)
        settings_layout.addWidget(QLabel("El gestor `flut` conserva el catálogo en el estado de Danenone y registra las aplicaciones instaladas en FreeDesktop."))
        cloud_label = QLabel("Cloud Danenone Devices comparte el mismo DaneDesk con el agente local. Las solicitudes de instalación remota se quedan pendientes hasta que las apruebes en este equipo.")
        cloud_label.setWordWrap(True)
        cloud_label.setStyleSheet("color:#9ac9bf;")
        settings_layout.addWidget(cloud_label)
        self.cloud_state = QLabel("Cloud Devices: sin conectar")
        settings_layout.addWidget(self.cloud_state)
        connect_cloud = QPushButton("Conectar este DaneDesk")
        connect_cloud.clicked.connect(self.connect_cloud_devices)
        settings_layout.addWidget(connect_cloud)
        refresh_cloud = QPushButton("Actualizar estado Cloud")
        refresh_cloud.clicked.connect(self.show_cloud_devices)
        settings_layout.addWidget(refresh_cloud)
        settings_layout.addStretch(1)
        self.stack.addWidget(settings)

        footer = QHBoxLayout()
        settings_button = QPushButton("Configuración")
        settings_button.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        footer.addWidget(settings_button)
        back_button = QPushButton("Catálogo")
        back_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        footer.addWidget(back_button)
        footer.addStretch(1)
        footer.addWidget(QLabel("Fluthin · Danenone"))
        layout.addLayout(footer)

    def refresh_catalog(self):
        self.status.setText("Examinando catalog/repo.list…")
        QApplication.processEvents()
        try:
            self.packages = manager.catalog(force=True)
            self.status.setText(f"{len(self.packages)} paquetes encontrados")
            self.filter_packages(self.search.text())
        except Exception as exc:
            self.status.setText("No se pudo actualizar el catálogo")
            QMessageBox.warning(self, "Catálogo", str(exc))

    def filter_packages(self, query: str):
        query = query.casefold().strip()
        self.list.clear()
        for package in self.packages:
            haystack = " ".join(package.get(key, "") for key in ("name", "app", "author", "description")).casefold()
            if query and query not in haystack:
                continue
            widget = PackageCard(package, self.install_package)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

    def install_package(self, package: dict[str, str]):
        reference = package.get("author", "") + "/" + package.get("app", "")
        try:
            result = manager.install(reference)
            QMessageBox.information(self, "Foundstore", f"Instalado: {result['metadata']['name']}\n{result['metadata']['version']}")
        except Exception as exc:
            QMessageBox.warning(self, "Instalación", str(exc))

    def connect_cloud_devices(self):
        server, accepted = QInputDialog.getText(self, "Cloud Danenone Devices", "Servidor HTTPS")
        if not accepted:
            return
        code, accepted = QInputDialog.getText(self, "Cloud Danenone Devices", "Código de pairing")
        if not accepted:
            return
        try:
            result = self.cloud_client.pair(server, code, self.windowTitle() or "DaneDesk")
            self.cloud_state.setText(f"Cloud Devices: conectado como {result['deviceId']}")
            QMessageBox.information(self, "Cloud Danenone Devices", "Este DaneDesk quedó vinculado. El agente local recibirá solicitudes de la tienda para aprobación local.")
        except CloudDevicesError as exc:
            QMessageBox.warning(self, "Cloud Danenone Devices", str(exc))

    def show_cloud_devices(self):
        try:
            state = self.cloud_client.status()
            self.cloud_state.setText(f"Cloud Devices: {state['displayName']} · {state['pendingActions']} solicitudes pendientes")
            QMessageBox.information(self, "Cloud Danenone Devices", f"Conectado a {state['server']}\nDaneDesk: {state['deviceId']}\nSolicitudes pendientes: {state['pendingActions']}\n\nLas instalaciones recibidas desde la nube requieren aprobación local mediante flut cloud approve.")
        except CloudDevicesError:
            self.cloud_state.setText("Cloud Devices: sin conectar")
            QMessageBox.information(self, "Cloud Danenone Devices", "Este Foundstore aún no está vinculado a un DaneDesk. Usa Configuración para conectarlo con un código de pairing.")


def main() -> int:
    app = QApplication(sys.argv)
    icon = ROOT / "static/logo_foundstore_transparent.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = StoreWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
