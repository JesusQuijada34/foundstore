from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import foundstore_api


class FoundstoreApiTests(unittest.TestCase):
    @patch("foundstore_api.requests.get")
    def test_catalog_normalizes_verified_stars_and_visuals(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "packages": [{"slug": "camera", "app": "camera", "author": "JesusQuijada34", "name": "Camera Selfie", "stars": 2, "visuals": {"icon": "https://example.test/icon.png"}}]
        }
        request.return_value = response
        package = foundstore_api.catalog()[0]
        self.assertEqual(package["slug"], "camera")
        self.assertEqual(package["stars"], 2)
        self.assertEqual(package["packageIcon"], "https://example.test/icon.png")

    @patch("foundstore_api.requests.get")
    def test_detail_preserves_readme_and_splash(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "package": {"app": "camera", "author": "JesusQuijada34", "readme": "# Camera", "stars": 2, "visuals": {"splash": "https://example.test/splash.png"}}
        }
        request.return_value = response
        package = foundstore_api.package_detail("camera")
        self.assertEqual(package["readme"], "# Camera")
        self.assertEqual(package["visuals"]["splash"], "https://example.test/splash.png")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
