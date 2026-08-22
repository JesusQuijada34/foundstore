from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from foundstore import DetailPanel, PackageBanner, grid_metrics, package_reference


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
        self.assertIsInstance(panel.preview_holder.itemAt(0).widget(), PackageBanner)
        self.assertEqual(panel.description.text(), "Prueba de catálogo")

    def test_grid_metrics_supports_requested_densities_without_overflow(self) -> None:
        self.assertEqual(grid_metrics(960, "macos", 3)[0], 3)
        self.assertEqual(grid_metrics(960, "measured", 4)[0], 4)
        columns, width, spacing = grid_metrics(960, "compact", 5)
        self.assertEqual(columns, 5)
        self.assertGreaterEqual(width, 150)
        self.assertEqual(spacing, 8)


if __name__ == "__main__":
    unittest.main()
