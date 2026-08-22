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

    def test_detail_action_visibility_tracks_installation_state(self) -> None:
        panel = DetailPanel(lambda: None, lambda *_: None)
        panel.set_action_state(False, False)
        self.assertFalse(panel.install_button.isHidden())
        self.assertTrue(panel.update_button.isHidden())
        panel.set_action_state(True, True)
        self.assertFalse(panel.update_button.isHidden())
        self.assertFalse(panel.uninstall_button.isHidden())
        panel.set_action_state(True, True, busy=True, status="Actualizando…")
        self.assertFalse(panel.cancel_button.isHidden())
        self.assertFalse(panel.progress.isHidden())

    def test_detail_copies_selected_readme_text(self) -> None:
        panel = DetailPanel(lambda: None, lambda *_: None)
        panel.readme.setPlainText("flut install JesusQuijada34/camera")
        cursor = panel.readme.textCursor()
        cursor.select(cursor.SelectionType.Document)
        panel.readme.setTextCursor(cursor)
        panel.copy_selected_code()
        self.assertEqual(QApplication.clipboard().text(), "flut install JesusQuijada34/camera")

    def test_detail_renders_markdown_readme(self) -> None:
        panel = DetailPanel(lambda: None, lambda *_: None)
        panel.set_package(
            {
                "name": "Camera",
                "author": "JesusQuijada34",
                "app": "camera",
                "description": "Cámara para pruebas.",
                "readme": "# Cámara\n\nUsa `flut install`.\n\n```bash\nflut install JesusQuijada34/camera\n```",
            }
        )
        rendered = panel.readme.document().toHtml().lower()
        self.assertIn("cámara", rendered)
        self.assertIn("flut install jesusquijada34/camera", rendered)
        self.assertIn("font-size:", rendered)


if __name__ == "__main__":
    unittest.main()
