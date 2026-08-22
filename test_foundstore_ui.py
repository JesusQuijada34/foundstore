from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from foundstore import DetailPanel, package_reference


class FoundstoreUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_package_reference_requires_complete_catalog_identity(self) -> None:
        self.assertEqual(package_reference({"author": "JesusQuijada34", "app": "camera"}), "JesusQuijada34/camera")
        self.assertEqual(package_reference({"author": "JesusQuijada34"}), "")
        self.assertEqual(package_reference({"app": "camera"}), "")

    def test_detail_panel_exposes_catalog_metadata_without_installing(self) -> None:
        panel = DetailPanel(lambda: None, lambda _: None)
        package = {"author": "JesusQuijada34", "app": "camera", "name": "Camera Selfie", "publisher": "Influent", "version": "v1.0", "platform": "AlphaCube", "description": "Prueba de catálogo"}
        panel.set_package(package)
        self.assertEqual(panel.title.text(), "Camera Selfie")
        self.assertIn("JesusQuijada34/camera", panel.meta.text())
        self.assertEqual(panel.description.text(), "Prueba de catálogo")


if __name__ == "__main__":
    unittest.main()
